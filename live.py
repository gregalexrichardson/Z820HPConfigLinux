"""Decode read-only ACPI objects from the Z820 legacy WMI probe."""
import re

GUID_TYPES = {
    '8232DE3C-663D-4327-A8F4-E293ADB9BF05': 'string',
    '8232DE3D-663D-4327-A8F4-E293ADB9BF05': 'integer',
    '8232DE3E-663D-4327-A8F4-E293ADB9BF05': 'enumeration',
    '8232DE3F-663D-4327-A8F4-E293ADB9BF05': 'ordered-list',
}
HEX_BYTES = re.compile(rb'(?:0x[0-9a-fA-F]{2})(?: 0x[0-9a-fA-F]{2})*\Z')


def decode_string(raw):
    # Z820 ACPI returns fixed-length byte arrays represented as ASCII hex.
    if HEX_BYTES.fullmatch(raw):
        raw = bytes(int(item, 16) for item in raw.split()).split(b'\0', 1)[0]
    return raw.decode('utf-8', errors='replace').strip()


def parse_capture(text):
    lines = iter(text.splitlines())
    def object_value(line, depth=0):
        if depth > 8:
            raise ValueError('ACPI object nesting exceeds limit')
        parts = line.split(' ', 2)
        if parts[0] == 'package':
            return [object_value(next(lines), depth + 1) for _ in range(int(parts[1]))]
        if parts[0] == 'integer':
            return int(parts[1])
        if parts[0] in ('string', 'buffer'):
            raw = bytes.fromhex(parts[2] if len(parts) == 3 else '')
            if len(raw) != int(parts[1]):
                raise ValueError('ACPI object length mismatch')
            return decode_string(raw) if parts[0] == 'string' else raw.hex()
        raise ValueError('unsupported ACPI object: ' + parts[0])

    result = []
    guid = None
    for line in lines:
        if line.startswith('guid '):
            guid = line.split()[1]
        elif line.startswith('instance '):
            fields = line.split()
            instance, status = int(fields[1]), int(fields[3])
            if status:
                raise ValueError(f'WMI query failed for {guid} instance {instance}: {status}')
            data = object_value(next(lines))
            if not isinstance(data, list) or len(data) < 9 or not isinstance(data[0], str):
                raise ValueError(f'unexpected WMI package for {guid} instance {instance}')
            item = {'name': data[0], 'value': data[1], 'path': data[2],
                    'read_only': bool(data[3]), 'type': GUID_TYPES.get(guid, 'unknown')}
            # Enumeration's derived CurrentValue follows two prerequisite strings.
            if item['type'] == 'enumeration' and len(data) >= 13:
                item['current_value'] = data[10]
                count = data[12]
                if not isinstance(count, int) or count < 0 or 13 + count > len(data):
                    raise ValueError(f'invalid enumeration count for {item["name"]}')
                item['possible_values'] = data[13:13 + count]
            if item['type'] == 'string' and len(data) >= 11:
                item['min_length'], item['max_length'] = data[9:11]
            if item['type'] == 'integer' and len(data) >= 12:
                item['lower_bound'], item['upper_bound'], item['int_value'] = data[9:12]
            if item['type'] == 'ordered-list' and len(data) >= 10:
                count = data[9]
                if not isinstance(count, int) or count < 0 or 10 + count > len(data):
                    raise ValueError(f'invalid ordered-list count for {item["name"]}')
                item['elements'] = data[10:10 + count]
            result.append(item)
        elif line:
            raise ValueError('unexpected capture line: ' + line[:80])
    return result


def encode_request(name, value, password=''):
    import struct
    output = bytearray()
    for text in (name, value, password):
        if '\0' in text:
            raise ValueError('NUL characters are not permitted')
        data = text.encode('utf-16-le')
        if len(data) > 1022:
            raise ValueError('field exceeds firmware buffer limit')
        output.extend(struct.pack('<H', len(data)))
        output.extend(data)
    return bytes(output)


def validate_change(rows, name, value):
    matches = [row for row in rows if row['name'].casefold() == name.casefold()]
    if len(matches) != 1:
        raise ValueError(f'expected exactly one matching setting, found {len(matches)}')
    row = matches[0]
    if row['read_only']:
        raise ValueError('setting is read-only')
    if 'password' in row['name'].casefold():
        raise ValueError('password-related settings are not supported')
    if row['type'] == 'enumeration':
        options = [v for v in row.get('possible_values', []) if v.casefold() == value.casefold()]
        if len(options) != 1:
            raise ValueError(f'invalid value; allowed: {row.get("possible_values", [])}')
        return row, options[0]
    if row['type'] == 'string':
        minimum, maximum = row.get('min_length'), row.get('max_length')
        if not isinstance(minimum, int) or not isinstance(maximum, int) or not minimum <= len(value) <= maximum:
            raise ValueError('string length is outside firmware limits or limits are unavailable')
        return row, value
    if row['type'] == 'integer':
        try:
            number = int(value, 10)
        except ValueError as exc:
            raise ValueError('expected a decimal integer') from exc
        low, high = row.get('lower_bound'), row.get('upper_bound')
        if not isinstance(low, int) or not isinstance(high, int) or not low <= number <= high:
            raise ValueError('integer is outside firmware limits or limits are unavailable')
        return row, str(number)
    if row['type'] == 'ordered-list':
        from collections import Counter
        current = row.get('elements')
        proposed = [part.strip() for part in value.split(',')]
        if not isinstance(current, list) or Counter(proposed) != Counter(current):
            raise ValueError('ordered list must be an exact permutation of current elements')
        return row, ','.join(proposed)
    raise ValueError('unsupported setting type')
