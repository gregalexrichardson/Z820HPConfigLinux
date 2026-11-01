import unittest
import hpconfig

class ConfigTests(unittest.TestCase):
    def test_utf16_roundtrip_and_change(self):
        data = b'\xff\xfe' + 'Headless Mode\r\n\t*Disable\r\n\tEnable\r\n'.encode('utf-16-le')
        text, enc, bom = hpconfig.decode(data)
        self.assertEqual(bom + text.encode(enc), data)
        self.assertEqual(hpconfig.select(text, 'Headless Mode', 'Enable'), 'Headless Mode\r\n\tDisable\r\n\t*Enable\r\n')
    def test_reject_invalid(self):
        for text, name, value in [('A\n\t*x\n\ty\n', 'A', 'z'), ('A\n\t*x\nA\n\t*y\n', 'A', 'x'), ('A\n\ttext\n', 'A', 'text')]:
            with self.assertRaises(ValueError): hpconfig.select(text, name, value)

if __name__ == '__main__': unittest.main()
