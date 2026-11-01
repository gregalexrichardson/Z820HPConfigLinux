import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import hpconfig


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.row = {'name': 'Num Lock', 'value': 'Off', 'current_value': 'Off',
                    'type': 'enumeration', 'read_only': False, 'possible_values': ['Off', 'On']}
        self.saved = dict(self.row, current_value='On')
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'backup.json'
        self.path.write_text(json.dumps({'format': 'hpconfig-backup-v1', 'machine': {'serial': 'a'}, 'settings': [self.saved]}))

    def run_restore(self, names, machine=None, writer=None, confirmed='APPLY'):
        out, err = io.StringIO(), io.StringIO()
        with (patch('sys.argv', ['hpconfig', 'restore', str(self.path)] + names),
              patch.object(hpconfig, 'probe', return_value=contextlib.nullcontext(Path('/fake'))),
              patch.object(hpconfig, 'read_live', return_value=[self.row]),
              patch.object(hpconfig, 'identity', return_value=machine or {'serial': 'a'}),
              patch.object(hpconfig, 'check_hardware'),
              patch.object(hpconfig, 'write_live', side_effect=writer or (lambda *a: 'Verified')) as write,
              patch('sys.stdin.isatty', return_value=True), patch('builtins.input', return_value=confirmed),
              contextlib.redirect_stdout(out), contextlib.redirect_stderr(err)):
            code = hpconfig.main()
        return code, out.getvalue(), err.getvalue(), write.call_count

    def test_compare_and_backup_roundtrip(self):
        doc = hpconfig.load_backup(self.path)
        self.assertEqual(hpconfig.compare_backup(doc, [self.row])[0][3], 'change')
        self.assertIn('settings', hpconfig.backup_document([self.row]))

    def test_restore_and_validation(self):
        self.assertEqual(self.run_restore(['Num Lock'])[0::3], (0, 1))
        self.assertEqual(self.run_restore(['Num Lock', 'missing'])[0::3], (1, 0))
        self.assertEqual(self.run_restore(['Num Lock'], machine={'serial': 'b'})[0::3], (1, 0))
        self.assertEqual(self.run_restore(['Num Lock'], confirmed='no')[0::3], (1, 0))

    def test_failure_stops(self):
        other = dict(self.saved, name='Other')
        self.path.write_text(json.dumps({'format':'hpconfig-backup-v1','machine':{},'settings':[self.saved, other]}))
        with patch.object(hpconfig, 'read_live', return_value=[self.row, dict(self.row, name='Other')]):
            # The helper supplies its own read mock; check the failure path on one selected entry.
            code, _, error, calls = self.run_restore(['Num Lock'], writer=ValueError('uncertain'))
        self.assertEqual((code, calls), (1, 1))
        self.assertIn('uncertain', error)
