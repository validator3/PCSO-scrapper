import re
import requests
import logging
from datetime import datetime, timezone, timedelta
from flask import Flask, jsonify
from bs4 import BeautifulSoup

app = Flask(__name__)

# ----------------------------------------------------------------------
# Logging setup – trace everything so you can debug easily on Railway
# ----------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------

def fetch_page():
    """Download the lotto results page and return stripped text lines."""
    url = "https://lottobot.ai/pcso-lotto-results/"
    logger.info("Fetching %s", url)
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    # Extract all visible text from the page
    text = soup.get_text(separator="\n")
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    logger.info("Fetched %d lines", len(lines))
    return lines


def find_block(lines, keyword, block_size=50):
    """
    Locate the first occurrence of `keyword` (case‑insensitive) and return
    a block of `block_size` lines starting from that line.
    """
    for i, line in enumerate(lines):
        if keyword.lower() in line.lower():
            logger.info("Keyword '%s' found at line %d: %s", keyword, i, line)
            return lines[i : i + block_size]
    logger.warning("Keyword '%s' not found", keyword)
    return []


def parse_big_game(lines, keyword, num_count):
    """
    Parse a big game (6/58, 6/55, etc.) from a 50‑line block.
    Returns dict with 'numbers', 'date', 'jackpot'.
    """
    block = find_block(lines, keyword, 50)
    if not block:
        return {"numbers": None, "date": None, "jackpot": None}
    block_text = " ".join(block)

    # Date: e.g., "Jun 24, 2026" (comma optional)
    date_match = re.search(
        r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2},?\s+\d{4}",
        block_text,
    )
    date = date_match.group(0) if date_match else None

    # Numbers: exactly num_count groups of 1‑ or 2‑digit numbers
    # Pattern: (num_count-1) groups of \d{1,2}\s+ then a final \d{1,2}
    pattern = r"\b(\d{1,2}\s+){%d}\d{1,2}\b" % (num_count - 1)
    num_match = re.search(pattern, block_text)
    numbers = None
    if num_match:
        numbers = "-".join(re.findall(r"\d{1,2}", num_match.group(0)))

    # Jackpot/Prize
    jackpot_match = re.search(
        r"(?:Jackpot|Prize):\s*([\d,]+(?:\.\d{2})?)", block_text
    )
    jackpot = jackpot_match.group(1) if jackpot_match else None

    logger.info(
        "Big game %s: date=%s, numbers=%s, jackpot=%s",
        keyword, date, numbers, jackpot,
    )
    return {"numbers": numbers, "date": date, "jackpot": jackpot}


def parse_slot_game(lines, keyword, num_count):
    """
    Parse a slot game (3D, 2D) from a 50‑line block.
    Returns dict with 'date' and 'slots' { '2PM': '...', '5PM': '...', '9PM': '...' }.
    """
    block = find_block(lines, keyword, 50)
    if not block:
        return {"date": None, "slots": {}}
    block_text = " ".join(block)

    # Date
    date_match = re.search(
        r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2},?\s+\d{4}",
        block_text,
    )
    date = date_match.group(0) if date_match else None

    slots = {}
    for slot in ["2PM", "5PM", "9PM"]:
        # Build regex: slot label followed by num_count digit groups.
        # The curly braces in \d{1,2} must be escaped for Python's .format()
        escaped_slot = re.escape(slot)
        # \d{{1,2}} -> literal {1,2} after .format()
        pattern = r"{}\s+" + r"\s+".join([r"(\d{{1,2}})"] * num_count)
        pattern = pattern.format(escaped_slot)
        match = re.search(pattern, block_text)
        if match:
            slots[slot] = "-".join(match.groups())

    logger.info("Slot game %s: date=%s, slots=%s", keyword, date, slots)
    return {"date": date, "slots": slots}


def get_draw_slot():
    """
    Determine if we are before or after the 9 PM draw.
    Philippines time (UTC+8). Returns "Pre‑draw" or "Post‑draw".
    """
    tz = timezone(timedelta(hours=8))
    now = datetime.now(tz)
    return "Post-draw" if now.hour >= 21 else "Pre-draw"


# ----------------------------------------------------------------------
# Flask routes
# ----------------------------------------------------------------------

@app.route("/")
def home():
    return jsonify({"status": "online", "endpoints": ["/results", "/message"]})


@app.route("/results")
def results():
    try:
        lines = fetch_page()
    except Exception as e:
        logger.error("Error fetching page: %s", e, exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500

    try:
        # Big games – (display name, keyword to find, number count)
        big_games = [
            ("6/58 Ultra Lotto", "Ultra Lotto", 6),
            ("6/55 Grand Lotto", "Grand Lotto", 6),
            ("6/49 Super Lotto", "Super Lotto", 6),
            ("6/45 Mega Lotto",  "Mega Lotto",  6),
            ("6/42 Lotto",       "6/42",        6),
            ("6D Lotto",         "6D Lotto",    6),
            ("4D Lotto",         "4D Lotto",    4),
        ]

        data = {
            "big_games": {},
            "slot_games": {},
            "draw_slot": get_draw_slot(),
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }

        # Parse each big game
        for name, keyword, count in big_games:
            data["big_games"][name] = parse_big_game(lines, keyword, count)

        # Slot games – careful with the keywords to avoid false matches
        data["slot_games"]["3D Lotto"] = parse_slot_game(lines, "3D Lotto", 3)
        data["slot_games"]["2D EZ2"]   = parse_slot_game(lines, "2D Lotto", 2)

        return jsonify({"success": True, "data": data})
    except Exception as e:
        logger.error("Error parsing results: %s", e, exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/message")
def message():
    """Return a human‑readable summary of latest results."""
    try:
        lines = fetch_page()
    except Exception as e:
        logger.error("Error fetching page for message: %s", e, exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500

    big = parse_big_game(lines, "Ultra Lotto", 6)
    if big["numbers"] and big["date"] and big["jackpot"]:
        msg = (
            f"PCSO 6/58 Ultra Lotto result for {big['date']}:\n"
            f"{big['numbers']} – Jackpot: ₱{big['jackpot']}"
        )
    else:
        msg = "PCSO results are not available at the moment."
    return jsonify({"success": True, "message": msg})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
