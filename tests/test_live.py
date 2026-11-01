import unittest
import live

class LiveTests(unittest.TestCase):
    def test_capture(self):
        def st(s):
            raw=s.encode(); return f'string {len(raw)} {raw.hex()}\n'
        name=' '.join(f'0x{x:02X}' for x in b'Headless Mode\0')
        text='guid 8232DE3E-663D-4327-A8F4-E293ADB9BF05 count 1\ninstance 0 status 0\npackage 15\n'
        text += st(name)+st('Disable,*Enable')+st('path')+'integer 0\ninteger 1\ninteger 0\ninteger 1\n'+st(' ')+st(' ')+'integer 0\n'+st('Enable')+'integer 1\ninteger 2\n'+st('Disable')+st('Enable')
        row=live.parse_capture(text)[0]
        self.assertEqual(row['name'], 'Headless Mode')
        self.assertEqual(row['current_value'], 'Enable')
        self.assertEqual(row['possible_values'], ['Disable','Enable'])
    def test_failed_query(self):
        with self.assertRaises(ValueError):
            live.parse_capture('guid x count 1\ninstance 0 status 5\n')

class WriteTests(unittest.TestCase):
    def test_encoding(self):
        self.assertEqual(live.encode_request('A', 'On'), b'\x02\x00A\x00\x04\x00O\x00n\x00\x00\x00')
        with self.assertRaises(ValueError): live.encode_request('bad\0', 'x')
    def test_validate(self):
        row={'name':'Test', 'type':'enumeration','read_only':False,'possible_values':['On','Off']}
        self.assertEqual(live.validate_change([row], 'test', 'on')[1], 'On')
        for rows, name, value in [([row],'test','other'), ([row,row],'test','on'), ([dict(row,read_only=True)],'test','on')]:
            with self.assertRaises(ValueError): live.validate_change(rows,name,value)
    def test_types(self):
        base={'name':'X','read_only':False,'value':'x'}
        row=dict(base,type='string',min_length=1,max_length=3)
        self.assertEqual(live.validate_change([row], 'x', 'ab')[1], 'ab')
        with self.assertRaises(ValueError): live.validate_change([row], 'x', 'abcd')
        row=dict(base,type='integer',lower_bound=2,upper_bound=10)
        self.assertEqual(live.validate_change([row], 'x', '03')[1], '3')
        with self.assertRaises(ValueError): live.validate_change([row], 'x', '11')
        row=dict(base,type='ordered-list',elements=['a','b'])
        self.assertEqual(live.validate_change([row], 'x', 'b,a')[1], 'b,a')
        with self.assertRaises(ValueError): live.validate_change([row], 'x', 'b,b')
