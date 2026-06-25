from flask import Flask, jsonify
from playwright.sync_api import sync_playwright
import re
import logging
from datetime import datetime
import pytz

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

MANILA_TZ = pytz.timezone('Asia/Manila')


def get_manila_time():
    return datetime.now(MANILA_TZ)


def scrape_pcso_results():
    """Scrape PCSO lotto results using Playwright"""
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-dev-shm-usage',
                '--disable-gpu'
            ]
        )
        page = browser.new_page()

        try:
            logger.info("Fetching lottobot.ai...")
            page.goto('https://lottobot.ai/pcso-lotto-results-today', 
                      wait_until='networkidle',
                      timeout=30000)

            # Wait for results to load
            page.wait_for_selector('text=6/42', timeout=15000)

            # Get full page text
            content = page.inner_text('body')
            logger.info(f"Page content length: {len(content)}")

            browser.close()
            return content

        except Exception as e:
            logger.error(f"Scraping error: {e}")
            browser.close()
            raise


def parse_results(content):
    """Parse the scraped text content into structured data"""
    lines = [l.strip() for l in content.split('\n') if l.strip()]
    
    now = get_manila_time()
    today_str = now.strftime('%b %-d, %Y')  # e.g. "Jun 24, 2026"
    
    results = {
        'scraped_at': now.strftime('%Y-%m-%d %H:%M:%S PHT'),
        'today': now.strftime('%B %d, %Y'),
        'draw_slot': get_draw_slot(now),
        'big_games': {},
        'slot_games': {}
    }

    def find_game_block(keyword, num_lines=15):
        for i, line in enumerate(lines):
            if keyword.lower() in line.lower():
                return lines[i:i+num_lines]
        return []

    def is_number_line(line, min_nums=2):
        parts = line.strip().split()
        return all(p.isdigit() for p in parts) and len(parts) >= min_nums

    def format_nums(line):
        return '-'.join(line.strip().split())

    def parse_date(line):
        months = ['Jan','Feb','Mar','Apr','May','Jun',
                  'Jul','Aug','Sep','Oct','Nov','Dec']
        for m in months:
            if m in line:
                return line.strip()
        return None

    # Parse big 6-ball games
    big_games = [
        ('6/58 Ultra Lotto', '6/58', 6),
        ('6/55 Grand Lotto', '6/55', 6),
        ('6/49 Super Lotto', '6/49', 6),
        ('6/45 Mega Lotto',  '6/45', 6),
        ('6/42 Lotto',       '6/42', 6),
        ('6D Lotto',         '6D',   6),
        ('4D Lotto',         '4D',   4),
    ]

    for game_name, keyword, num_count in big_games:
        block = find_game_block(keyword)
        if not block:
            results['big_games'][game_name] = {'numbers': None, 'date': None, 'jackpot': None}
            continue

        date = None
        numbers = None
        jackpot = None

        for i, line in enumerate(block):
            # Find date
            if not date:
                d = parse_date(line)
                if d and any(m in d for m in ['Jan','Feb','Mar','Apr','May',
                                               'Jun','Jul','Aug','Sep','Oct','Nov','Dec']):
                    date = d

            # Find numbers after date
            if date and not numbers and is_number_line(line, num_count):
                parts = line.strip().split()
                if len(parts) >= num_count:
                    numbers = '-'.join(parts[:num_count])

            # Find jackpot/prize
            if numbers and not jackpot:
                if 'Jackpot:' in line or 'Prize:' in line:
                    jackpot = line.replace('Jackpot:', '').replace('Prize:', '').split('Winners:')[0].strip()

        results['big_games'][game_name] = {
            'numbers': numbers,
            'date': date,
            'jackpot': jackpot
        }

    # Parse slot games (3D and 2D)
    slot_game_keywords = [
        ('3D Lotto', '3D (Suertres) Lotto Today', 3),
        ('2D EZ2',   '2D Lotto Today', 2),
    ]

    time_slots = ['2PM', '5PM', '9PM']

    for game_name, keyword, num_count in slot_game_keywords:
        block = find_game_block(keyword, 20)
        if not block:
            results['slot_games'][game_name] = {'date': None, 'slots': {}}
            continue

        date = None
        slots = {}
        current_slot = None

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

        results['slot_games'][game_name] = {
            'date': date,
            'slots': slots
        }

    return results


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


def format_message(results):
    """Format results into a clean Messenger/Telegram message"""
    lines = []
    lines.append(f"PCSO Results - {results['today']}")
    lines.append(f"({results['draw_slot']})")
    lines.append('')

    # Big games
    for game_name, data in results['big_games'].items():
        if data['numbers']:
            date_str = f" ({data['date']})" if data['date'] else ''
            jackpot = f" | {data['jackpot']}" if data['jackpot'] else ''
            lines.append(f"{game_name}{date_str}: {data['numbers']}{jackpot}")
        else:
            lines.append(f"{game_name}: No draw today")

    lines.append('')

    # Slot games
    for game_name, data in results['slot_games'].items():
        if data['slots']:
            date_str = f" ({data['date']})" if data['date'] else ''
            lines.append(f"{game_name}{date_str}:")
            for slot in ['2PM', '5PM', '9PM']:
                result = data['slots'].get(slot, 'pending')
                lines.append(f"  {slot}: {result}")
        else:
            lines.append(f"{game_name}: No draw today")

    lines.append('')
    lines.append('Good luck!')

    return '\n'.join(lines)


# ─── Routes ───────────────────────────────────────────────────────────────────

@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({'status': 'ok', 'time': get_manila_time().strftime('%Y-%m-%d %H:%M:%S PHT')})


@app.route('/results', methods=['GET'])
def get_results():
    """Main endpoint — returns structured JSON results"""
    try:
        content = scrape_pcso_results()
        results = parse_results(content)
        return jsonify({
            'success': True,
            'data': results
        })
    except Exception as e:
        logger.error(f"Error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/message', methods=['GET'])
def get_message():
    """Returns pre-formatted message ready to send to Messenger/Telegram"""
    try:
        content = scrape_pcso_results()
        results = parse_results(content)
        message = format_message(results)
        return jsonify({
            'success': True,
            'message': message
        })
    except Exception as e:
        logger.error(f"Error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=False)
