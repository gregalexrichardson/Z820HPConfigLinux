#!/usr/bin/env python3
"""Inspect and edit HP BIOS settings and F10 replicated-setup exports."""
import argparse
import contextlib
import fcntl
import stat
import json
import getpass
import os
import subprocess
import live
import sys
from pathlib import Path


def decode(data):
    if data.startswith((b'\xff\xfe', b'\xfe\xff')):
        return data.decode('utf-16'), 'utf-16-le' if data[:2] == b'\xff\xfe' else 'utf-16-be', data[:2]
    if b'\x00' in data:
        raise ValueError('UTF-16 without a byte order mark is not supported')
    return data.decode('utf-8-sig'), 'utf-8', b'\xef\xbb\xbf' if data.startswith(b'\xef\xbb\xbf') else b''


def settings(text):
    lines = text.splitlines(keepends=True)
    sections = []
    for i, line in enumerate(lines):
        if line.strip() and not line[0].isspace() and not line.startswith(';'):
            end = i + 1
            while end < len(lines) and (not lines[end].strip() or lines[end][0].isspace()):
                end += 1
            sections.append((line.strip(), i, end))
    return lines, sections


def select(text, name, value):
    lines, sections = settings(text)
    matches = [(a, b) for n, a, b in sections if n.casefold() == name.casefold()]
    if len(matches) != 1:
        raise ValueError(f'expected exactly one setting named {name!r}; found {len(matches)}')
    start, end = matches[0]
    candidates = []
    for i in range(start + 1, end):
        content = lines[i].strip()
        if content and content != '--':
            candidates.append((i, content.removeprefix('*')))
    chosen = [i for i, v in candidates if v.casefold() == value.casefold()]
    if len(chosen) != 1 or sum(lines[i].lstrip().startswith('*') for i, _ in candidates) != 1:
        raise ValueError('setting is not an unambiguous enumeration with the requested value')
    for i, _ in candidates:
        line = lines[i]
        prefix = len(line) - len(line.lstrip(' \t'))
        head, rest = line[:prefix], line[prefix:]
        if rest.startswith('*'):
            rest = rest[1:]
        if i == chosen[0]:
            rest = '*' + rest
        lines[i] = head + rest
    return ''.join(lines)


@contextlib.contextmanager
def probe():
    if os.geteuid() != 0:
        raise ValueError('live access requires root; run with sudo')
    # Serialize module lifetime, preflight, firmware write and readback across
    # invocations; otherwise one command can unload another's interface.
    lock_fd = os.open('/run/lock/hpconfig-linux.lock',
                      os.O_CREAT | os.O_RDWR | os.O_CLOEXEC | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(lock_fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_nlink != 1 or info.st_mode & 0o022:
            raise ValueError('unsafe lock file; check /run/lock/hpconfig-linux.lock')
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        module = Path(os.environ.get('HPCONFIG_MODULE', Path(__file__).resolve().parent / 'kernel/hpconfig_probe.ko'))
        loaded = Path('/sys/module/hpconfig_probe').exists()
        if not loaded:
            if not module.exists():
                raise ValueError('probe not built; run make -C kernel LLVM=1')
            subprocess.run(['insmod', str(module)], check=True)
        try:
            yield Path('/sys/kernel/debug/hpconfig_legacy')
        finally:
            if not loaded:
                subprocess.run(['rmmod', 'hpconfig_probe'], check=True)
    finally:
        os.close(lock_fd)


def read_live(directory):
    return live.parse_capture((directory / 'raw').read_text())


def check_hardware():
    product = Path('/sys/class/dmi/id/product_name').read_text().strip()
    if product != 'HP Z820 Workstation':
        raise ValueError(f'live writes are supported only on the tested HP Z820 Workstation; found {product!r}')
    required = set(live.GUID_TYPES) | {'C9B590D8-E7E4-4DC5-BB0F-CB8A3522027E'}
    present = {p.name[:36].upper() for p in Path('/sys/bus/wmi/devices').iterdir()}
    if not required.issubset(present):
        raise ValueError('required legacy WMI interfaces are unavailable')


def identity():
    result = {}
    for key, name in [('product', 'product_name'), ('serial', 'product_serial')]:
        try:
            value = (Path('/sys/class/dmi/id') / name).read_text().strip()
        except OSError:
            continue
        if value and value.casefold() not in ('none', 'unknown', 'not specified', 'to be filled by o.e.m.'):
            result[key] = value
    return result


def backup_document(rows):
    return {'format': 'hpconfig-backup-v1', 'machine': identity(), 'settings': rows}


def load_backup(path):
    document = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(document, dict) or document.get('format') != 'hpconfig-backup-v1' or not isinstance(document.get('machine'), dict) or not isinstance(document.get('settings'), list):
        raise ValueError('invalid or unsupported backup')
    if any(not isinstance(row, dict) or not isinstance(row.get('name'), str) or not isinstance(row.get('value'), str) or not isinstance(row.get('current_value', row.get('value')), str) for row in document['settings']):
        raise ValueError('invalid backup settings')
    return document


def compare_backup(document, rows):
    result = []
    for saved in document['settings']:
        matches = [row for row in rows if row['name'].casefold() == saved['name'].casefold()]
        value = saved.get('current_value', saved['value'])
        if len(matches) != 1:
            result.append((saved['name'], value, None, 'missing or ambiguous'))
            continue
        row = matches[0]
        current = row.get('current_value', row['value'])
        try:
            live.validate_change(rows, saved['name'], value)
            status = 'unchanged' if current == value else 'change'
        except (ValueError, TypeError, AttributeError) as exc:
            status = f'unsupported: {exc}'
        result.append((saved['name'], value, current, status))
    return result


def write_live(directory, rows, name, value, password=None):
    check_hardware()
    row, chosen = live.validate_change(rows, name, value)
    current_value = row.get('current_value', row['value'])
    if current_value == chosen:
        return f"Already set: {row['name']} = {chosen}"
    password = '<utf-16/>' + password if password is not None else ''
    request = live.encode_request(row['name'], chosen, password)
    del password
    fd = os.open(directory / 'set', os.O_RDWR)
    try:
        try:
            sent = os.write(fd, request)
        except OSError as exc:
            raise ValueError(f'firmware request failed; the change may have applied: {exc}') from exc
        if sent != len(request):
            raise ValueError('short firmware request write; the change may have applied')
        try:
            result = os.read(fd, 128).decode('ascii').strip()
        except (OSError, UnicodeError) as exc:
            raise ValueError(f'firmware response could not be read; the change may have applied: {exc}') from exc
    finally:
        os.close(fd)
    if result != 'return 0':
        raise ValueError(f'firmware rejected or failed write: {result}')
    try:
        found = [item for item in read_live(directory) if item['name'] == row['name']]
    except (OSError, UnicodeError, ValueError, StopIteration) as exc:
        raise ValueError(f'firmware reported success but read-back failed; the change may have applied: {exc}') from exc
    if len(found) != 1:
        raise ValueError('firmware reported success but the setting could not be uniquely read back')
    after = found[0]
    readback = after.get('current_value', after['value'])
    if readback != chosen:
        raise ValueError(f"firmware returned success but reads {readback!r}; a reboot may be required")
    return f"Verified: {row['name']} = {chosen} (a reboot may still be required)"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='cmd', required=True)
    show = sub.add_parser('list', help='list exported settings')
    show.add_argument('file', type=Path)
    show.add_argument('--filter', default='')
    current = sub.add_parser('live', help='read live BIOS settings via the legacy WMI probe (root required)')
    current.add_argument('--filter', default='')
    current.add_argument('--json', action='store_true')
    sub.add_parser('tui', help='interactive terminal interface (root required)')
    change = sub.add_parser('set-live', help='change a live BIOS setting (root required)')
    change.add_argument('name')
    change.add_argument('value')
    change.add_argument('--password', action='store_true', help='prompt for the BIOS setup password')
    backup = sub.add_parser('backup', help='save live settings as JSON')
    backup.add_argument('file', type=Path)
    compare = sub.add_parser('compare', help='compare a backup with live settings')
    compare.add_argument('file', type=Path)
    restore = sub.add_parser('restore', help='preview and restore selected settings')
    restore.add_argument('file', type=Path)
    restore.add_argument('names', nargs='+', help='setting names to restore')
    restore.add_argument('--password', action='store_true')
    edit = sub.add_parser('set', help='write an edited copy of an exported configuration')
    edit.add_argument('file', type=Path)
    edit.add_argument('name')
    edit.add_argument('value')
    edit.add_argument('-o', '--output', required=True, type=Path)
    args = parser.parse_args()
    try:
        if args.cmd in ('backup', 'compare', 'restore'):
            document = None if args.cmd == 'backup' else load_backup(args.file)
            with probe() as directory:
                rows = read_live(directory)
                if args.cmd == 'backup':
                    with os.fdopen(os.open(args.file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w', encoding='utf-8') as output:
                        json.dump(backup_document(rows), output, indent=2)
                        output.write('\n')
                    print(f'Backup saved to {args.file}; it may contain sensitive information.')
                    return 0
                differences = compare_backup(document, rows)
                if args.cmd == 'compare':
                    for name, value, current, status in differences:
                        print(f'{name}: {current!r} -> {value!r} ({status})')
                    return 0
                check_hardware()
                current_identity = identity()
                for key, value in document['machine'].items():
                    if key in current_identity and current_identity[key] != value:
                        raise ValueError(f'backup machine {key} does not match this machine')
                selected = []
                for name in args.names:
                    matches = [item for item in differences if item[0].casefold() == name.casefold()]
                    if len(matches) != 1 or matches[0][3] not in ('change', 'unchanged'):
                        raise ValueError(f'cannot restore {name!r}: missing, ambiguous or unsupported')
                    if any(item[0].casefold() == name.casefold() for item in selected):
                        raise ValueError(f'duplicate selection: {name}')
                    selected.append(matches[0])
                for name, value, current, status in selected:
                    print(f'{name}: {current!r} -> {value!r} ({status})')
                if not sys.stdin.isatty() or input('Type APPLY to confirm: ') != 'APPLY':
                    raise ValueError('restore cancelled')
                password = getpass.getpass('BIOS setup password: ') if args.password else None
                for index, (name, value, _, _) in enumerate(selected):
                    try:
                        print(write_live(directory, rows, name, value, password))
                        rows = read_live(directory)
                    except (OSError, ValueError, UnicodeError, StopIteration) as exc:
                        print(f'Failed: {name}: {exc}', file=sys.stderr)
                        for remaining in selected[index + 1:]:
                            print(f'Unattempted: {remaining[0]}', file=sys.stderr)
                        return 1
                return 0
        if args.cmd == 'tui':
            if not sys.stdin.isatty() or not sys.stdout.isatty():
                raise ValueError('tui requires an interactive terminal')
            import tui
            with probe() as directory:
                tui.run(directory, read_live, write_live)
            return 0
        if args.cmd in ('live', 'set-live'):
            with probe() as directory:
                rows = read_live(directory)
                if args.cmd == 'set-live':
                    password = getpass.getpass('BIOS setup password: ') if args.password else None
                    print(write_live(directory, rows, args.name, args.value, password))
                    return 0
            rows = [row for row in rows if args.filter.casefold() in row['name'].casefold()]
            if args.json:
                print(json.dumps(rows, indent=2))
            else:
                for row in rows:
                    print(f"{row['name']}: {row.get('current_value', row['value'])}")
            return 0
        text, encoding, bom = decode(args.file.read_bytes())
        if args.cmd == 'list':
            lines, sections = settings(text)
            for name, start, end in sections:
                if args.filter.casefold() in name.casefold():
                    print(''.join(lines[start:end]), end='')
        else:
            updated = select(text, args.name, args.value)
            with args.output.open('xb') as f:
                f.write(bom + updated.encode(encoding))
            print(f'Wrote {args.output}; firmware has not been changed.')
    except (OSError, UnicodeError, ValueError, subprocess.CalledProcessError, StopIteration) as exc:
        print(f'hpconfig: {exc}', file=sys.stderr)
        return 1
    return 0

if __name__ == '__main__':
    sys.exit(main())
