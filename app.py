from flask import Flask, jsonify
import requests
from bs4 import BeautifulSoup
import logging
from datetime import datetime
import pytz
import re
import traceback

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

    for tag in soup(['script', 'style', 'nav', 'footer']):
        tag.decompose()

    text = soup.get_text(separator='\n')
    lines = [l.strip() for l in text.split('\n') if l.strip()]

    logger.info(f"Got {len(lines)} lines of content")
    logger.info(f"First 20 lines: {lines[:20]}")
    return lines


def parse_date(line):
    months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
              'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
    if any(m in line for m in months) and re.search(r'\d{4}', line):
        return line.strip()
    return None


def find_block(lines, keyword, num_lines=50):
    """Find a block of lines starting from the line containing keyword."""
    for i, line in enumerate(lines):
        if keyword.lower() in line.lower():
            block = lines[i:i + num_lines]
            logger.info(f"Found block for '{keyword}' at line {i}, first few lines: {block[:5]}")
            return block
    logger.warning(f"No block found for '{keyword}'")
    return []


def parse_big_game(lines, keyword, num_count):
    try:
        block = find_block(lines, keyword, 50)
        if not block:
            return {'numbers': None, 'date': None, 'jackpot': None}

        block_text = ' '.join(block)

        date_match = re.search(
            r'(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2},?\s+\d{4}',
            block_text
        )
        date = date_match.group(0) if date_match else None

        pattern = r'\b(\d{1,2}\s+){%d}\d{1,2}\b' % (num_count - 1)
        num_match = re.search(pattern, block_text)
        numbers = None
        if num_match:
            numbers = '-'.join(re.findall(r'\d{1,2}', num_match.group(0)))

        jackpot_match = re.search(r'(?:Jackpot|Prize):\s*([\d,]+(?:\.\d{2})?)', block_text)
        jackpot = jackpot_match.group(1) if jackpot_match else None

        return {'numbers': numbers, 'date': date, 'jackpot': jackpot}

    except Exception as e:
        logger.error(f"Error in parse_big_game for '{keyword}': {e}")
        logger.error(traceback.format_exc())
        raise Exception(f"parse_big_game error: {e}")


def parse_slot_game(lines, keyword, num_count):
    try:
        block = find_block(lines, keyword, 50)
        if not block:
            return {'date': None, 'slots': {}}

        block_text = ' '.join(block)

        date_match = re.search(
            r'(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2},?\s+\d{4}',
            block_text
        )
        date = date_match.group(0) if date_match else None

        slots = {}
        for slot in ['2PM', '5PM', '9PM']:
            # Build pattern without using .format() to avoid braces conflict with regex quantifiers
            num_pattern = r'\s+'.join([r'(\d{1,2})'] * num_count)
            pattern = re.escape(slot) + r'\s+' + num_pattern
            match = re.search(pattern, block_text)
            if match:
                slots[slot] = '-'.join(match.groups())

        return {'date': date, 'slots': slots}

    except Exception as e:
        logger.error(f"Error in parse_slot_game for '{keyword}': {e}")
        logger.error(traceback.format_exc())
        raise Exception(f"parse_slot_game error: {e}")


def parse_results(lines):
    now = get_manila_time()

    results = {
        'scraped_at': now.strftime('%Y-%m-%d %H:%M:%S PHT'),
        'today': now.strftime('%B %d, %Y'),
        'draw_slot': get_draw_slot(now),
        'big_games': {},
        'slot_games': {}
    }

    big_games = [
        ('6/58 Ultra Lotto', 'Ultra Lotto', 6),
        ('6/55 Grand Lotto', 'Grand Lotto', 6),
        ('6/49 Super Lotto', 'Super Lotto', 6),
        ('6/45 Mega Lotto',  'Mega Lotto',  6),
        ('6/42 Lotto',       '6/42',        6),
        ('6D Lotto',         '6D Lotto',    6),
        ('4D Lotto',         '4D Lotto',    4),
    ]

    for game_name, keyword, num_count in big_games:
        results['big_games'][game_name] = parse_big_game(lines, keyword, num_count)

    results['slot_games']['3D Lotto'] = parse_slot_game(lines, '3D Lotto', 3)
    results['slot_games']['2D EZ2']   = parse_slot_game(lines, '2D Lotto', 2)

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
        logger.error(f"Route error: {e}")
        logger.error(traceback.format_exc())
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/message')
def get_message():
    try:
        lines   = scrape_pcso_results()
        results = parse_results(lines)
        message = format_message(results)
        return jsonify({'success': True, 'message': message})
    except Exception as e:
        logger.error(f"Route error: {e}")
        logger.error(traceback.format_exc())
        return jsonify({'success': False, 'error': str(e)}), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=False)
