from flask import Flask, jsonify
import requests
from bs4 import BeautifulSoup
import logging
from datetime import datetime
import pytz
import re

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

MANILA_TZ = pytz.timezone('Asia/Manila')


def get_manila_time():
    return datetime.now(MANILA_TZ)


def get_draw_slot(now):
    hour = now.hour
    if hour < 14:
        return 'Pre-draw'
    elif hour < 17:
        return '2PM Draw'
    elif hour < 21:
        return '5PM Draw'
    else:
        return '9PM Draw'


def scrape_pcso_results():
    """Scrape PCSO lotto results using requests + BeautifulSoup"""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
    }

    logger.info("Fetching lottobot.ai...")
    response = requests.get(
        'https://lottobot.ai/pcso-lotto-results-today',
        headers=headers,
        timeout=30
    )
    response.raise_for_status()

    soup = BeautifulSoup(response.text, 'html.parser')

    # Remove script and style tags
    for tag in soup(['script', 'style', 'nav', 'footer']):
        tag.decompose()

    # Get clean text
    text = soup.get_text(separator='\n')
    lines = [l.strip() for l in text.split('\n') if l.strip()]

    logger.info(f"Got {len(lines)} lines of content")
    return lines


def is_number_line(line, min_nums=2):
    parts = line.strip().split()
    return all(p.isdigit() for p in parts) and len(parts) >= min_nums


def parse_date(line):
    months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
              'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
    if any(m in line for m in months) and re.search(r'\d{4}', line):
        return line.strip()
    return None


def find_block(lines, keyword, num_lines=20):
    for i, line in enumerate(lines):
        if keyword.lower() in line.lower():
            return lines[i:i + num_lines]
    return []


def parse_big_game(lines, keyword, num_count):
    block = find_block(lines, keyword, 20)
    if not block:
        return {'numbers': None, 'date': None, 'jackpot': None}

    date = None
    numbers = None
    jackpot = None

    for line in block:
        if not date:
            d = parse_date(line)
            if d:
                date = d

        if date and not numbers and is_number_line(line, num_count):
            parts = line.strip().split()
            if len(parts) >= num_count:
                numbers = '-'.join(parts[:num_count])

        if numbers and not jackpot:
            if 'Jackpot:' in line or 'Prize:' in line:
                jackpot = line.replace('Jackpot:', '').replace('Prize:', '').split('Winners:')[0].strip()

    return {'numbers': numbers, 'date': date, 'jackpot': jackpot}


def parse_slot_game(lines, keyword, num_count):
    block = find_block(lines, keyword, 25)
    if not block:
        return {'date': None, 'slots': {}}

    date = None
    slots = {}
    current_slot = None
    time_slots = ['2PM', '5PM', '9PM']

    for line in block:
        if not date:
            d = parse_date(line)
            if d:
                date = d

        if line in time_slots:
            current_slot = line
        elif current_slot and is_number_line(line, num_count):
            parts = line.strip().split()
            if len(parts) >= num_count:
                slots[current_slot] = '-'.join(parts[:num_count])
                current_slot = None

    return {'date': date, 'slots': slots}


def parse_results(lines):
    now = get_manila_time()

    results = {
        'scraped_at': now.strftime('%Y-%m-%d %H:%M:%S PHT'),
        'today': now.strftime('%B %d, %Y'),
        'draw_slot': get_draw_slot(now),
        'big_games': {},
        'slot_games': {}
    }

    # Big games
    big_games = [
        ('6/58 Ultra Lotto', '6/58 Ultra Lotto', 6),
        ('6/55 Grand Lotto', '6/55 Grand Lotto', 6),
        ('6/49 Super Lotto', '6/49 Super Lotto', 6),
        ('6/45 Mega Lotto',  '6/45 Mega Lotto',  6),
        ('6/42 Lotto',       '6/42 Lotto',        6),
        ('6D Lotto',         '6D Lotto',          6),
        ('4D Lotto',         '4D Lotto',          4),
    ]

    for game_name, keyword, num_count in big_games:
        results['big_games'][game_name] = parse_big_game(lines, keyword, num_count)

    # Slot games
    results['slot_games']['3D Lotto'] = parse_slot_game(lines, '3D', 3)
    results['slot_games']['2D EZ2']   = parse_slot_game(lines, '2D Lotto Today', 2)

    return results


def format_message(results):
    lines = []
    lines.append(f"PCSO Results - {results['today']}")
    lines.append(f"({results['draw_slot']})")
    lines.append('')

    for game_name, data in results['big_games'].items():
        if data['numbers']:
            date_str = f" ({data['date']})" if data['date'] else ''
            jackpot   = f" | {data['jackpot']}" if data['jackpot'] else ''
            lines.append(f"{game_name}{date_str}: {data['numbers']}{jackpot}")
        else:
            lines.append(f"{game_name}: No draw today")

    lines.append('')

    for game_name, data in results['slot_games'].items():
        if data['slots']:
            date_str = f" ({data['date']})" if data['date'] else ''
            lines.append(f"{game_name}{date_str}:")
            for slot in ['2PM', '5PM', '9PM']:
                lines.append(f"  {slot}: {data['slots'].get(slot, 'pending')}")
        else:
            lines.append(f"{game_name}: No draw today")

    lines.append('')
    lines.append('Good luck!')

    return '\n'.join(lines)


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route('/health')
def health():
    return jsonify({'status': 'ok', 'time': get_manila_time().strftime('%Y-%m-%d %H:%M:%S PHT')})


@app.route('/results')
def get_results():
    try:
        lines   = scrape_pcso_results()
        results = parse_results(lines)
        return jsonify({'success': True, 'data': results})
    except Exception as e:
        logger.error(f"Error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/message')
def get_message():
    try:
        lines   = scrape_pcso_results()
        results = parse_results(lines)
        message = format_message(results)
        return jsonify({'success': True, 'message': message})
    except Exception as e:
        logger.error(f"Error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=False)
