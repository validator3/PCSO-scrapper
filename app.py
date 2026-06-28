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

# Keywords to search for each game in the page text
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
# Helpers
# ----------------------------------------------------------------------

def get_draw_slot():
    now = datetime.now(PH_TZ)
    if now.hour >= 21:
        return "Post-draw (9PM)"
    elif now.hour >= 17:
        return "Post-draw (5PM)"
    elif now.hour >= 14:
        return "Post-draw (2PM)"
    else:
        return "Pre-draw"


def fetch_page(url=SOURCE_URL):
    logger.info("Fetching %s", url)
    resp = requests.get(url, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    logger.info("Fetched %d bytes", len(resp.text))
    return resp.text


def extract_lines(html):
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(separator="\n")
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    return lines


def find_block(lines, keywords, block_size=60):
    """Find first occurrence of any keyword and return surrounding lines."""
    for i, line in enumerate(lines):
        for kw in keywords:
            if kw.lower() in line.lower():
                logger.info("Keyword '%s' found at line %d: %s", kw, i, line)
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
    """Extract exactly `count` 1-or-2-digit numbers in sequence."""
    pattern = r"(?<!\d)(\d{1,2})(?!\d)"
    all_nums = re.findall(pattern, text)
    # Slide a window looking for a valid sequence
    for i in range(len(all_nums) - count + 1):
        chunk = all_nums[i:i + count]
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
    date = extract_date(block_text)
    numbers = extract_numbers(block_text, num_count)
    jackpot = extract_jackpot(block_text)

    logger.info("%s → date=%s numbers=%s jackpot=%s", display_name, date, numbers, jackpot)
    return {"numbers": numbers, "date": date, "jackpot": jackpot}


def parse_slot_game(lines, display_name, keywords, num_count):
    block = find_block(lines, keywords)
    if not block:
        return {"date": None, "slots": {}}

    block_text = " ".join(block)
    date = extract_date(block_text)
    slots = {}

    for draw_time in DRAW_TIMES:
        # Look for pattern like "2PM 1-2" or "9PM 5 8 3"
        pattern = re.escape(draw_time) + r"[\s:–-]*([\d\s\-]+)"
        match = re.search(pattern, block_text, re.IGNORECASE)
        if match:
            nums = re.findall(r"\d{1,2}", match.group(1))[:num_count]
            if len(nums) == num_count:
                slots[draw_time] = "-".join(nums)

    logger.info("%s → date=%s slots=%s", display_name, date, slots)
    return {"date": date, "slots": slots}


# ----------------------------------------------------------------------
# Routes
# ----------------------------------------------------------------------

@app.route("/")
def home():
    return jsonify({
        "status": "online",
        "source": SOURCE_URL,
        "endpoints": ["/results", "/message", "/debug"],
        "note": "Results available after 2PM, 5PM, 9PM Philippine time"
    })


@app.route("/results")
def results():
    try:
        html = fetch_page()
        lines = extract_lines(html)
    except Exception as e:
        logger.error("Fetch error: %s", e, exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500

    try:
        big_games = {}
        for display_name, keywords, count in BIG_GAME_KEYWORDS:
            big_games[display_name] = parse_big_game(lines, display_name, keywords, count)

        slot_games = {}
        for display_name, keywords, count in SLOT_GAME_KEYWORDS:
            slot_games[display_name] = parse_slot_game(lines, display_name, keywords, count)

        return jsonify({
            "success": True,
            "data": {
                "big_games":  big_games,
                "slot_games": slot_games,
                "draw_slot":  get_draw_slot(),
                "fetched_at": datetime.now(timezone.utc).isoformat(),
            }
        })
    except Exception as e:
        logger.error("Parse error: %s", e, exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/message")
def message():
    try:
        html = fetch_page()
        lines = extract_lines(html)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

    for display_name, keywords, count in BIG_GAME_KEYWORDS:
        g = parse_big_game(lines, display_name, keywords, count)
        if g["numbers"] and g["date"]:
            jp = f" — Jackpot: ₱{g['jackpot']}" if g.get("jackpot") else ""
            return jsonify({
                "success": True,
                "message": f"PCSO {display_name} result for {g['date']}:\n{g['numbers']}{jp}"
            })

    return jsonify({
        "success": True,
        "message": (
            "PCSO results are not yet available. "
            "Please check after 2:05 PM, 5:05 PM, or 9:05 PM Philippine time."
        )
    })


@app.route("/debug")
def debug():
    """Shows raw page lines and tables for troubleshooting."""
    try:
        html = fetch_page()
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

    lines = extract_lines(html)

    soup = BeautifulSoup(html, "html.parser")
    tables = []
    for i, tbl in enumerate(soup.find_all("table")):
        rows = []
        for row in tbl.find_all("tr"):
            cols = [td.get_text(strip=True) for td in row.find_all(["td", "th"])]
            if cols:
                rows.append(cols)
        tables.append({"table_index": i, "rows": rows[:20]})

    return jsonify({
        "success": True,
        "draw_slot": get_draw_slot(),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "total_lines": len(lines),
        "text_lines": lines[:200],
        "tables": tables,
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
