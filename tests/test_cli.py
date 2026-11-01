import contextlib
import io
import unittest
from pathlib import Path
from unittest.mock import patch
import hpconfig


class LiveWriteFlowTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(hpconfig, 'check_hardware')
        patcher.start()
        self.addCleanup(patcher.stop)
        self.before = {'name':'Num Lock', 'type':'enumeration', 'read_only':False,
                       'value':'*Off,On', 'current_value':'Off', 'possible_values':['Off','On']}
        self.after = dict(self.before, current_value='On', value='Off,*On')

    def run_cli(self, reads, result=b'return 0\n', value='On'):
        output, error = io.StringIO(), io.StringIO()
        with (patch('sys.argv', ['hpconfig','set-live','Num Lock',value]),
              patch.object(hpconfig, 'probe', return_value=contextlib.nullcontext(Path('/fake'))),
              patch.object(hpconfig, 'read_live', side_effect=reads),
              patch.object(hpconfig.os, 'open', return_value=123),
              patch.object(hpconfig.os, 'write', side_effect=lambda fd, data: len(data)) as write,
              patch.object(hpconfig.os, 'read', return_value=result),
              patch.object(hpconfig.os, 'close'),
              contextlib.redirect_stdout(output), contextlib.redirect_stderr(error)):
            code = hpconfig.main()
            return code, output.getvalue(), error.getvalue(), write.call_count

    def test_success_requires_matching_readback(self):
        code, out, err, writes = self.run_cli([[self.before],[self.after]])
        self.assertEqual((code, writes), (0, 1))
        self.assertIn('Verified', out)

    def test_rejected_does_not_report_success(self):
        code, out, err, writes = self.run_cli([[self.before]], b'return 6\n')
        self.assertEqual((code, writes), (1, 1))
        self.assertIn('return 6', err)
        self.assertNotIn('Verified', out)

    def test_mismatch_does_not_report_success(self):
        code, out, err, writes = self.run_cli([[self.before],[self.before]])
        self.assertEqual((code, writes), (1, 1))
        self.assertIn('reads', err)

    def test_invalid_and_already_set_do_not_write(self):
        self.assertEqual(self.run_cli([[self.before]], value='invalid')[3], 0)
        code, out, _, writes = self.run_cli([[self.before]], value='Off')
        self.assertEqual((code, writes), (0, 0))
        self.assertIn('Already set', out)

    def test_write_transport_failure_closes_descriptor(self):
        error = io.StringIO()
        with (patch('sys.argv', ['hpconfig','set-live','Num Lock','On']),
              patch.object(hpconfig, 'probe', return_value=contextlib.nullcontext(Path('/fake'))),
              patch.object(hpconfig, 'read_live', return_value=[self.before]),
              patch.object(hpconfig.os, 'open', return_value=123),
              patch.object(hpconfig.os, 'write', side_effect=OSError('I/O failed')),
              patch.object(hpconfig.os, 'close') as close,
              contextlib.redirect_stderr(error)):
            self.assertEqual(hpconfig.main(), 1)
            close.assert_called_once_with(123)
            self.assertIn('I/O failed', error.getvalue())

    def test_setting_that_disappears_after_write_is_not_success(self):
        code, out, err, writes = self.run_cli([[self.before],[]])
        self.assertEqual((code, writes), (1, 1))
        self.assertNotIn('Verified', out)
        self.assertIn('could not be uniquely read back', err)

    def test_password_is_prompted_and_not_reported(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        with (patch('sys.argv', ['hpconfig','set-live','Num Lock','On','--password']),
              patch.object(hpconfig, 'probe', return_value=contextlib.nullcontext(Path('/fake'))),
              patch.object(hpconfig, 'read_live', side_effect=[[self.before],[self.after]]),
              patch.object(hpconfig.getpass, 'getpass', return_value='secret'),
              patch.object(hpconfig.os, 'open', return_value=123),
              patch.object(hpconfig.os, 'write', side_effect=lambda fd, data: len(data)) as write,
              patch.object(hpconfig.os, 'read', return_value=b'return 0\n'),
              patch.object(hpconfig.os, 'close'),
              contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr)):
            self.assertEqual(hpconfig.main(), 0)
            self.assertIn('<utf-16/>secret'.encode('utf-16-le'), write.call_args.args[1])
            self.assertNotIn('secret', stdout.getvalue()+stderr.getvalue())

    def test_failed_readback_reports_uncertain_state(self):
        code, out, err, writes = self.run_cli([[self.before], OSError('read failed')])
        self.assertEqual((code, writes), (1, 1))
        self.assertIn('change may have applied', err)
        self.assertNotIn('Verified', out)

    def test_response_failure_reports_uncertain_state(self):
        err = io.StringIO()
        with (patch('sys.argv', ['hpconfig','set-live','Num Lock','On']),
              patch.object(hpconfig, 'probe', return_value=contextlib.nullcontext(Path('/fake'))),
              patch.object(hpconfig, 'read_live', return_value=[self.before]),
              patch.object(hpconfig.os, 'open', return_value=123),
              patch.object(hpconfig.os, 'write', side_effect=lambda fd, data: len(data)),
              patch.object(hpconfig.os, 'read', side_effect=OSError('failed')),
              patch.object(hpconfig.os, 'close'), contextlib.redirect_stderr(err)):
            self.assertEqual(hpconfig.main(), 1)
            self.assertIn('change may have applied', err.getvalue())
