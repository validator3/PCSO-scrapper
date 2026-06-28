import re
import requests
import logging
from datetime import datetime, timezone, timedelta
from flask import Flask, jsonify
from bs4 import BeautifulSoup

app = Flask(__name__)

# ----------------------------------------------------------------------
# Logging
# ----------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------
# Constants
# ----------------------------------------------------------------------
SOURCE_URL = "https://www.lottopcso.com/"
PH_TZ = timezone(timedelta(hours=8))

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

BIG_GAME_KEYWORDS = [
    ("6/58 Ultra Lotto", ["6/58", "Ultra Lotto 6/58", "Ultra Lotto"], 6),
    ("6/55 Grand Lotto", ["6/55", "Grand Lotto 6/55", "Grand Lotto"], 6),
    ("6/49 Super Lotto", ["6/49", "Super Lotto 6/49", "Super Lotto"], 6),
    ("6/45 Mega Lotto",  ["6/45", "Mega Lotto 6/45",  "Mega Lotto"],  6),
    ("6/42 Lotto",       ["6/42", "Lotto 6/42"],                      6),
    ("6D Lotto",         ["6D Lotto", "6-Digit"],                     6),
    ("4D Lotto",         ["4D Lotto", "4-Digit"],                     4),
]

SLOT_GAME_KEYWORDS = [
    ("3D Lotto", ["Swertres", "3D Lotto", "3-Digit"], 3),
    ("2D EZ2",   ["EZ2", "2D Lotto", "2-Digit"],      2),
]

DRAW_TIMES = ["11AM", "2PM", "4PM", "5PM", "9PM"]

# ----------------------------------------------------------------------
# Time / context helpers
# ----------------------------------------------------------------------

def get_ph_now():
    return datetime.now(PH_TZ)


def get_draw_context():
    now = get_ph_now()
    today_str     = now.strftime("%B %d, %Y")
    yesterday     = now - timedelta(days=1)
    yesterday_str = yesterday.strftime("%B %d, %Y")

    if now.hour >= 21:
        return {
            "draw_slot":         "Post-draw (9PM)",
            "is_todays_result":  True,
            "result_date_label": today_str,
            "status_message":    f"Today's PCSO Lotto Results ({today_str}) - 9PM Draw",
        }
    elif now.hour >= 17:
        return {
            "draw_slot":         "Post-draw (5PM)",
            "is_todays_result":  True,
            "result_date_label": today_str,
            "status_message":    f"Today's PCSO Lotto Results ({today_str}) - 5PM Draw",
        }
    elif now.hour >= 14:
        return {
            "draw_slot":         "Post-draw (2PM)",
            "is_todays_result":  True,
            "result_date_label": today_str,
            "status_message":    f"Today's PCSO Lotto Results ({today_str}) - 2PM Draw",
        }
    else:
        return {
            "draw_slot":         "Pre-draw",
            "is_todays_result":  False,
            "result_date_label": yesterday_str,
            "status_message":    f"Latest PCSO Results ({yesterday_str}) | Next draw today at 2:00 PM PH time",
        }


# ----------------------------------------------------------------------
# Scraping helpers
# ----------------------------------------------------------------------

def fetch_page(url=SOURCE_URL):
    logger.info("Fetching %s", url)
    resp = requests.get(url, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    logger.info("Fetched %d bytes", len(resp.text))
    return resp.text


def extract_lines(html):
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(separator="\n")
    return [l.strip() for l in text.split("\n") if l.strip()]


def find_block(lines, keywords, block_size=60):
    for i, line in enumerate(lines):
        for kw in keywords:
            if kw.lower() in line.lower():
                logger.info("Keyword '%s' found at line %d", kw, i)
                return lines[i: i + block_size]
    logger.warning("Keywords %s not found", keywords)
    return []


def extract_date(text):
    match = re.search(
        r"(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
        r"Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
        r"\.?\s+\d{1,2},?\s+\d{4}",
        text, re.IGNORECASE
    )
    return match.group(0) if match else None


def extract_numbers(text, count):
    nums = re.findall(r"(?<!\d)(\d{1,2})(?!\d)", text)
    for i in range(len(nums) - count + 1):
        chunk = nums[i: i + count]
        if all(1 <= int(n) <= 58 for n in chunk):
            return "-".join(chunk)
    return None


def extract_jackpot(text):
    match = re.search(
        r"(?:Jackpot|Prize|jackpot)[:\s]*([\d,]+(?:\.\d{2})?)", text, re.IGNORECASE
    )
    return match.group(1) if match else None


def parse_big_game(lines, display_name, keywords, num_count):
    block = find_block(lines, keywords)
    if not block:
        return {"numbers": None, "date": None, "jackpot": None}
    block_text = " ".join(block)
    result = {
        "numbers": extract_numbers(block_text, num_count),
        "date":    extract_date(block_text),
        "jackpot": extract_jackpot(block_text),
    }
    logger.info("%s -> %s", display_name, result)
    return result


def parse_slot_game(lines, display_name, keywords, num_count):
    block = find_block(lines, keywords)
    if not block:
        return {"date": None, "slots": {}}
    block_text = " ".join(block)
    slots = {}
    for draw_time in DRAW_TIMES:
        pattern = re.escape(draw_time) + r"[\s:-]*([\d\s-]+)"
        match = re.search(pattern, block_text, re.IGNORECASE)
        if match:
            nums = re.findall(r"\d{1,2}", match.group(1))[:num_count]
            if len(nums) == num_count:
                slots[draw_time] = "-".join(nums)
    result = {"date": extract_date(block_text), "slots": slots}
    logger.info("%s -> %s", display_name, result)
    return result


def has_any_results(big_games, slot_games):
    for g in big_games.values():
        if g.get("numbers"):
            return True
    for g in slot_games.values():
        if g.get("slots"):
            return True
    return False


def detect_actual_result_date(big_games, slot_games):
    for g in big_games.values():
        if g.get("date"):
            return g["date"]
    for g in slot_games.values():
        if g.get("date"):
            return g["date"]
    return None


# ----------------------------------------------------------------------
# Routes
# ----------------------------------------------------------------------

@app.route("/")
def home():
    return jsonify({
        "status":    "online",
        "source":    SOURCE_URL,
        "endpoints": ["/results", "/message", "/debug"],
        "note":      "Draws at 2PM, 5PM, 9PM Philippine time (UTC+8)",
    })


@app.route("/results")
def results():
    try:
        html  = fetch_page()
        lines = extract_lines(html)
    except Exception as e:
        logger.error("Fetch error: %s", e, exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500

    try:
        big_games  = {
            name: parse_big_game(lines, name, kws, cnt)
            for name, kws, cnt in BIG_GAME_KEYWORDS
        }
        slot_games = {
            name: parse_slot_game(lines, name, kws, cnt)
            for name, kws, cnt in SLOT_GAME_KEYWORDS
        }

        ctx = get_draw_context()
        actual_date = detect_actual_result_date(big_games, slot_games)
        if actual_date:
            ctx["result_date_label"] = actual_date

        data_available = has_any_results(big_games, slot_games)

        return jsonify({
            "success": True,
            "meta": {
                "draw_slot":         ctx["draw_slot"],
                "is_todays_result":  ctx["is_todays_result"],
                "result_date":       ctx["result_date_label"],
                "status_message":    ctx["status_message"],
                "data_available":    data_available,
                "fetched_at":        datetime.now(timezone.utc).isoformat(),
                "ph_time":           get_ph_now().strftime("%Y-%m-%d %H:%M:%S %Z"),
            },
            "data": {
                "big_games":  big_games,
                "slot_games": slot_games,
            }
        })
    except Exception as e:
        logger.error("Parse error: %s", e, exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/message")
def message():
    """
    Returns a clean, Messenger-friendly message.
    Uses | as line separator so JSON stays valid and
    n8n can pass it without breaking.
    """
    try:
        html  = fetch_page()
        lines = extract_lines(html)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

    ctx = get_draw_context()

    # Build message lines using | as separator (no newlines in JSON)
    parts = [ctx["status_message"], ""]

    found_any = False
    for display_name, keywords, count in BIG_GAME_KEYWORDS:
        g = parse_big_game(lines, display_name, keywords, count)
        if g["numbers"] and g["date"]:
            jp = f" | Jackpot: P{g['jackpot']}" if g.get("jackpot") else ""
            parts.append(f"{display_name} ({g['date']}): {g['numbers']}{jp}")
            found_any = True

    for display_name, keywords, count in SLOT_GAME_KEYWORDS:
        g = parse_slot_game(lines, display_name, keywords, count)
        if g.get("slots"):
            slot_text = " | ".join(f"{t}: {n}" for t, n in g["slots"].items())
            parts.append(f"{display_name} ({g.get('date', 'N/A')}): {slot_text}")
            found_any = True

    if not found_any:
        parts.append("No results found. The site may be updating - please try again shortly.")

    # Join with newline — Flask jsonify will properly escape these
    # so they arrive as \n in JSON and render as line breaks in Messenger
    final_message = "\n".join(parts)

    return jsonify({
        "success":          True,
        "is_todays_result": ctx["is_todays_result"],
        "draw_slot":        ctx["draw_slot"],
        "message":          final_message,
    })


@app.route("/debug")
def debug():
    try:
        html  = fetch_page()
        lines = extract_lines(html)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

    soup   = BeautifulSoup(html, "html.parser")
    tables = []
    for i, tbl in enumerate(soup.find_all("table")):
        rows = []
        for row in tbl.find_all("tr"):
            cols = [td.get_text(strip=True) for td in row.find_all(["td", "th"])]
            if cols:
                rows.append(cols)
        tables.append({"table_index": i, "rows": rows[:20]})

    ctx = get_draw_context()

    return jsonify({
        "success": True,
        "meta": {
            "draw_slot":        ctx["draw_slot"],
            "is_todays_result": ctx["is_todays_result"],
            "result_date":      ctx["result_date_label"],
            "status_message":   ctx["status_message"],
            "ph_time":          get_ph_now().strftime("%Y-%m-%d %H:%M:%S %Z"),
            "fetched_at":       datetime.now(timezone.utc).isoformat(),
        },
        "total_lines": len(lines),
        "text_lines":  lines[:200],
        "tables":      tables,
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
