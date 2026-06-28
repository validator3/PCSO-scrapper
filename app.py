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
PCSO_URL = "https://www.pcso.gov.ph/SearchLottoResult.aspx"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}

PH_TZ = timezone(timedelta(hours=8))

# Map display names to keywords that appear in PCSO table
GAME_NAME_MAP = {
    "Ultra Lotto 6/58": "6/58 Ultra Lotto",
    "Grand Lotto 6/55": "6/55 Grand Lotto",
    "Super Lotto 6/49": "6/49 Super Lotto",
    "Mega Lotto 6/45":  "6/45 Mega Lotto",
    "Lotto 6/42":       "6/42 Lotto",
    "6D Lotto":         "6D Lotto",
    "4D Lotto":         "4D Lotto",
    "3D Lotto":         "3D Lotto",
    "2D Lotto":         "2D EZ2",
}

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


def fetch_soup():
    """Fetch PCSO results page and return BeautifulSoup object."""
    logger.info("Fetching PCSO results from %s", PCSO_URL)
    resp = requests.get(PCSO_URL, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    logger.info("Page fetched successfully (%d bytes)", len(resp.text))
    return soup


def parse_results(soup):
    """
    Parse the PCSO lotto results table.
    Returns a dict with big_games and slot_games.
    """
    big_games = {v: {"numbers": None, "jackpot": None, "date": None}
                 for v in GAME_NAME_MAP.values() if "EZ2" not in v and "3D" not in v}
    slot_games = {
        "3D Lotto": {"date": None, "slots": {}},
        "2D EZ2":   {"date": None, "slots": {}},
    }

    # Try to find any table on the page
    tables = soup.find_all("table")
    logger.info("Found %d tables on page", len(tables))

    result_table = None
    for table in tables:
        text = table.get_text()
        # Look for a table that contains lotto game names
        if any(keyword in text for keyword in ["6/58", "6/55", "6/42", "4D", "3D", "2D"]):
            result_table = table
            logger.info("Found lotto results table")
            break

    if not result_table:
        logger.warning("No results table found — page structure may have changed")
        return big_games, slot_games

    rows = result_table.find_all("tr")
    logger.info("Table has %d rows", len(rows))

    for row in rows:
        cols = [td.get_text(strip=True) for td in row.find_all(["td", "th"])]
        if len(cols) < 3:
            continue

        logger.info("Row: %s", cols)

        raw_game = cols[0]
        display_name = GAME_NAME_MAP.get(raw_game)

        if not display_name:
            # Try partial match
            for pcso_name, mapped_name in GAME_NAME_MAP.items():
                if pcso_name.lower() in raw_game.lower() or raw_game.lower() in pcso_name.lower():
                    display_name = mapped_name
                    break

        if not display_name:
            continue

        # Numbers are usually in col[1], jackpot col[2], date col[3]
        numbers_raw = cols[1] if len(cols) > 1 else None
        jackpot_raw = cols[2] if len(cols) > 2 else None
        date_raw    = cols[3] if len(cols) > 3 else None

        # Clean numbers — replace spaces/dashes with consistent dash separator
        numbers = None
        if numbers_raw:
            found = re.findall(r"\d{1,2}", numbers_raw)
            if found:
                numbers = "-".join(found)

        # Clean jackpot — strip non-numeric except comma/dot
        jackpot = None
        if jackpot_raw:
            jp = re.sub(r"[^\d,.]", "", jackpot_raw)
            jackpot = jp if jp else None

        # Clean date
        date = None
        if date_raw:
            dm = re.search(
                r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\.?\s+\d{1,2},?\s+\d{4}",
                date_raw, re.IGNORECASE
            )
            date = dm.group(0) if dm else date_raw

        # Route to correct bucket
        if display_name in ("3D Lotto", "2D EZ2"):
            # For slot games, try to detect draw time from extra columns
            slot_key = None
            for col in cols:
                if "2PM" in col or "2 PM" in col:
                    slot_key = "2PM"
                elif "5PM" in col or "5 PM" in col:
                    slot_key = "5PM"
                elif "9PM" in col or "9 PM" in col:
                    slot_key = "9PM"

            game_data = slot_games[display_name]
            if date and not game_data["date"]:
                game_data["date"] = date
            if numbers and slot_key:
                game_data["slots"][slot_key] = numbers
            elif numbers:
                # If no slot detected, store under whatever slots exist
                for s in ["9PM", "5PM", "2PM"]:
                    if s not in game_data["slots"]:
                        game_data["slots"][s] = numbers
                        break
        else:
            if display_name in big_games:
                big_games[display_name] = {
                    "numbers": numbers,
                    "jackpot": jackpot,
                    "date":    date,
                }

    return big_games, slot_games


# ----------------------------------------------------------------------
# Routes
# ----------------------------------------------------------------------

@app.route("/")
def home():
    return jsonify({
        "status": "online",
        "endpoints": ["/results", "/message", "/debug"],
        "source": PCSO_URL,
    })


@app.route("/results")
def results():
    try:
        soup = fetch_soup()
    except Exception as e:
        logger.error("Fetch error: %s", e, exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500

    try:
        big_games, slot_games = parse_results(soup)
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
    """Return a plain-text summary of the biggest game available."""
    try:
        soup = fetch_soup()
        big_games, _ = parse_results(soup)
    except Exception as e:
        logger.error("Message endpoint error: %s", e, exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500

    # Try games from biggest jackpot down
    for game in ["6/58 Ultra Lotto", "6/55 Grand Lotto", "6/49 Super Lotto",
                 "6/45 Mega Lotto", "6/42 Lotto", "6D Lotto", "4D Lotto"]:
        g = big_games.get(game, {})
        if g.get("numbers") and g.get("date"):
            jp = f" — Jackpot: ₱{g['jackpot']}" if g.get("jackpot") else ""
            msg = f"PCSO {game} result for {g['date']}:\n{g['numbers']}{jp}"
            return jsonify({"success": True, "message": msg})

    return jsonify({
        "success": True,
        "message": "PCSO results are not yet available. Please check after 2:05 PM, 5:05 PM, or 9:05 PM Philippine time."
    })


@app.route("/debug")
def debug():
    """
    Raw debug endpoint — returns the first 150 lines of page text
    plus all table row contents so you can verify parsing.
    """
    try:
        soup = fetch_soup()
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

    # Raw text lines
    text = soup.get_text(separator="\n")
    lines = [l.strip() for l in text.split("\n") if l.strip()]

    # All table rows
    table_data = []
    for i, table in enumerate(soup.find_all("table")):
        rows = []
        for row in table.find_all("tr"):
            cols = [td.get_text(strip=True) for td in row.find_all(["td", "th"])]
            if cols:
                rows.append(cols)
        table_data.append({"table_index": i, "rows": rows[:30]})

    return jsonify({
        "success": True,
        "text_lines": lines[:150],
        "tables": table_data,
        "draw_slot": get_draw_slot(),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
