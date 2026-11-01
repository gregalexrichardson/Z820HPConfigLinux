"""Interactive terminal interface for the legacy HP firmware backend."""
import curses
import textwrap


def _draw(win, y, x, text, attr=0):
    h, w = win.getmaxyx()
    if y < 0 or y >= h or x >= w - 1:
        return
    try:
        win.addnstr(y, x, str(text).replace('\n', ' '), max(0, w - x - 1), attr)
    except curses.error:
        pass


def _screen(win, title, lines, footer=''):
    win.erase()
    h, _ = win.getmaxyx()
    _draw(win, 0, 0, title, curses.A_BOLD)
    for i, line in enumerate(lines[:max(0, h - 3)], 1):
        _draw(win, i, 0, line)
    _draw(win, h - 1, 0, footer)
    win.refresh()


def _input(win, title, initial='', secret=False):
    value = initial
    while True:
        _screen(win, title, ['(Escape cancels; Enter accepts)', '*' * len(value) if secret else value])
        k = win.get_wch()
        if k in ('\x1b',): return None
        if k in ('\n', '\r', curses.KEY_ENTER): return value
        if k in ('\b', '\x7f', curses.KEY_BACKSPACE): value = value[:-1]
        elif isinstance(k, str) and k.isprintable(): value += k


def _choose(win, row):
    options = row.get('possible_values', [])
    if not options:
        return None
    current = row.get('current_value', '')
    selected = options.index(current) if current in options else 0
    while True:
        h, _ = win.getmaxyx()
        visible = max(1, h - 4)
        start = max(0, selected - visible + 1)
        lines = [('> ' if i == selected else '  ') + option for i, option in enumerate(options)][start:start + visible]
        _screen(win, row['name'], lines, 'Up/Down select   Enter choose   Esc cancel')
        k = win.get_wch()
        if k in ('\x1b', 'q'): return None
        if k in ('\n', '\r', curses.KEY_ENTER): return options[selected]
        if k in (curses.KEY_UP, 'k'): selected = max(0, selected - 1)
        if k in (curses.KEY_DOWN, 'j'): selected = min(len(options) - 1, selected + 1)


def _detail(win, row):
    offset = 0
    while True:
        h, width = win.getmaxyx()
        lines = []
        for key, value in row.items():
            text = f"{key}: {', '.join(map(str, value)) if isinstance(value, list) else value}"
            lines.extend(textwrap.wrap(text, width=max(1, width - 2), replace_whitespace=False) or [''])
        visible = max(1, h - 3)
        offset = min(offset, max(0, len(lines) - visible))
        _screen(win, 'Setting details', lines[offset:offset + visible], 'Up/Down scroll   q or Esc back')
        key = win.get_wch()
        if key in ('q', '\x1b', '\n', '\r'): return
        if key in (curses.KEY_UP, 'k'): offset = max(0, offset - 1)
        if key in (curses.KEY_DOWN, 'j'): offset = min(max(0, len(lines) - visible), offset + 1)
        if key == curses.KEY_NPAGE: offset = min(max(0, len(lines) - visible), offset + visible)
        if key == curses.KEY_PPAGE: offset = max(0, offset - visible)


def _wait(win, title, message):
    _screen(win, title, [message], 'Press any key to continue')
    win.get_wch()


def _loading(win, message):
    _screen(win, 'HP BIOS settings', [message])


def _run(win, directory, read_live, write_live):
    win.keypad(True)
    try: curses.curs_set(0)
    except curses.error: pass
    _loading(win, 'Reading firmware settings; this may take a while...')
    rows = read_live(directory)
    filter_text = ''
    selected = 0
    offset = 0
    status = ''
    while True:
        h, w = win.getmaxyx()
        shown = [r for r in rows if filter_text.casefold() in (r['name'] + ' ' + r['path']).casefold()]
        selected = min(selected, max(0, len(shown) - 1))
        height = max(1, h - 5)
        if selected < offset: offset = selected
        if selected >= offset + height: offset = selected - height + 1
        offset = min(offset, max(0, len(shown) - height))
        win.erase()
        _draw(win, 0, 0, f'HP BIOS settings  ({len(shown)}/{len(rows)})  Filter: {filter_text}', curses.A_BOLD)
        if h < 7 or w < 30:
            _draw(win, 2, 0, 'Enlarge terminal; q quits')
        else:
            for idx in range(offset, min(len(shown), offset + height)):
                row = shown[idx]
                value = row.get('current_value', row['value'])
                tag = ' [read-only]' if row['read_only'] else ''
                _draw(win, 2 + idx - offset, 0, f"{row['name']}: {value}{tag}", curses.A_REVERSE if idx == selected else 0)
            if shown:
                row = shown[selected]
                _draw(win, h - 3, 0, f"{row['type']}  {row['path']}")
            _draw(win, h - 2, 0, status)
            _draw(win, h - 1, 0, '↑↓ navigate  / filter  d details  Enter edit  r refresh  q quit')
        win.refresh()
        k = win.get_wch()
        if k in ('q', 'Q'): return
        if h < 7 or w < 30: continue
        if k == '/':
            entered = _input(win, 'Filter by name or BIOS path')
            if entered is not None: filter_text, selected, offset = entered, 0, 0
        elif k in (curses.KEY_UP, 'k'): selected = max(0, selected - 1)
        elif k in (curses.KEY_DOWN, 'j'): selected = min(len(shown) - 1, selected + 1) if shown else 0
        elif k == curses.KEY_NPAGE: selected = min(len(shown) - 1, selected + height) if shown else 0
        elif k == curses.KEY_PPAGE: selected = max(0, selected - height)
        elif k in ('d', 'D') and shown:
            _detail(win, shown[selected])
        elif k in ('r', 'R'):
            _loading(win, 'Refreshing firmware settings...')
            try: rows, status = read_live(directory), 'Refreshed.'
            except (OSError, ValueError, UnicodeError, StopIteration) as e: status = f'Refresh failed: {e}'
        elif k in ('\n', '\r', curses.KEY_ENTER) and shown:
            row = shown[selected]
            if row['read_only'] or 'password' in row['name'].casefold():
                status = 'This setting cannot be edited here.'
                continue
            old = row.get('current_value', row['value'])
            new = _choose(win, row) if row['type'] == 'enumeration' else _input(win, f"New value for {row['name']}", old)
            if new is None: continue
            if new == old:
                status = 'Value unchanged.'
                continue
            _screen(win, 'Confirm BIOS change', [row['name'], f'Current: {old}', f'New: {new}', 'Press y to apply, p to apply with BIOS password, or any other key to cancel.'])
            answer = win.get_wch()
            if answer not in ('y', 'Y', 'p', 'P'): continue
            password = _input(win, 'BIOS setup password', secret=True) if answer in ('p', 'P') else None
            if answer in ('p', 'P') and password is None: continue
            _loading(win, 'Writing and verifying firmware setting...')
            try:
                status = write_live(directory, rows, row['name'], new, password)
            except (OSError, ValueError, UnicodeError, StopIteration) as e:
                status = f'Write failed: {e}'
            finally:
                password = None
            _wait(win, 'BIOS change result', status)
            _loading(win, 'Refreshing firmware settings...')
            try: rows = read_live(directory)
            except (OSError, ValueError, UnicodeError, StopIteration) as e: status += f'; refresh failed: {e}'


def run(directory, read_live, write_live):
    curses.wrapper(_run, directory, read_live, write_live)
