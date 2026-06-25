def parse_big_game(lines, keyword, num_count):
    block = find_block(lines, keyword, 20)
    if not block:
        return {'numbers': None, 'date': None, 'jackpot': None}

    block_text = ' '.join(block)

    # Extract date
    date_match = re.search(r'(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2},?\s+\d{4}', block_text)
    date = date_match.group(0) if date_match else None

    # Extract numbers (exactly num_count numbers, each 1-2 digits)
    pattern = r'\b(\d{1,2}\s+){%d}\d{1,2}\b' % (num_count - 1)
    num_match = re.search(pattern, block_text)
    numbers = None
    if num_match:
        numbers = '-'.join(re.findall(r'\d{1,2}', num_match.group(0)))

    # Extract jackpot / prize
    jackpot_match = re.search(r'(?:Jackpot|Prize):\s*([\d,]+(?:\.\d{2})?)', block_text)
    jackpot = jackpot_match.group(1) if jackpot_match else None

    return {'numbers': numbers, 'date': date, 'jackpot': jackpot}


def parse_slot_game(lines, keyword, num_count):
    block = find_block(lines, keyword, 25)
    if not block:
        return {'date': None, 'slots': {}}

    block_text = ' '.join(block)

    # Extract date
    date_match = re.search(r'(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2},?\s+\d{4}', block_text)
    date = date_match.group(0) if date_match else None

    slots = {}
    for slot in ['2PM', '5PM', '9PM']:
        # Build pattern: slot name followed by num_count numbers
        pattern = r'{}\s+' + r'\s+'.join([r'(\d{1,2})'] * num_count)
        pattern = pattern.format(re.escape(slot))
        match = re.search(pattern, block_text)
        if match:
            slots[slot] = '-'.join(match.groups())

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

    # Big games – using shorter, more reliable keywords
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

    # Slot games
    results['slot_games']['3D Lotto'] = parse_slot_game(lines, '3D', 3)
    results['slot_games']['2D EZ2']   = parse_slot_game(lines, '2D Lotto', 2)   # changed from '2D Lotto Today'

    return results
