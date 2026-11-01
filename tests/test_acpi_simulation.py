"""Optional ACPI simulation; no firmware or real hardware is accessed."""
import os
from pathlib import Path
import re
import subprocess
import unittest

import live


@unittest.skipUnless(all(os.environ.get(k) for k in ('HP_ACPIEXEC','HP_DSDT','HP_SSDT')), 'set HP_ACPIEXEC, HP_DSDT, HP_SSDT to run ACPI simulation')
class ACPISimulation(unittest.TestCase):
    def test_wmad_extracts_length_prefixed_arguments(self):
        name, value, password = 'Num Lock State at Power-On', 'On', 'test'
        payload = live.encode_request(name, value, password)
        cmd = ('execute \\_SB.WMID.WMAD 0 1 (' + ' '.join(f'{b:02x}' for b in payload) +
               '); dump \\_SB.WMID.GETN; dump \\_SB.WMID.GETV; dump \\_SB.WMID.GETP')
        proc = subprocess.run([os.environ['HP_ACPIEXEC'], '-di', '-b', cmd,
                               os.environ['HP_DSDT'], os.environ['HP_SSDT']],
                              capture_output=True, text=True, timeout=30, check=True)
        self.assertIn('Evaluation of \\_SB.WMID.WMAD returned object', proc.stdout)
        for marker, expected in [('GETN', name), ('GETV', value), ('GETP', password)]:
            parent = f'Parent Node :'
            sections = [part for part in proc.stdout.split(parent) if f'[{marker}]' in part[:100]]
            self.assertEqual(len(sections), 1, marker)
            dumped = bytearray()
            for line in sections[0].splitlines()[1:]:
                match = re.match(r'\s*[0-9A-F]{4}: ((?:[0-9A-F]{2} ){1,16})', line)
                if match:
                    dumped.extend(bytes.fromhex(match.group(1)))
                elif dumped:
                    break
            self.assertTrue(dumped.startswith(expected.encode('utf-16-le') + b'\x00\x00'), marker)
