"""Parse the real inspected unit plus our drop-in without running either."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

HERE = Path(__file__).parent

class UnitValidation(unittest.TestCase):
    def test_upstream_unit_and_hooks_pass_systemd_validation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            upstream = (HERE / 'coolercontrold.service').read_text()
            # Only executables are substituted; production unit semantics are preserved.
            (root / 'coolercontrold.service').write_text(upstream.replace('/usr/bin/coolercontrold', '/usr/bin/true'))
            dropin = root / 'coolercontrold.service.d'
            dropin.mkdir()
            text = (HERE / 'pt31553.conf').read_text()
            (dropin / 'pt31553.conf').write_text(text.replace('/usr/lib/pt31553-fan-control/session', '/usr/bin/true'))
            result = subprocess.run(['systemd-analyze', 'verify', '--man=no', str(root / 'coolercontrold.service')],
                                    env={**os.environ, 'SYSTEMD_UNIT_PATH': str(root) + ':/usr/lib/systemd/system'},
                                    text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            for key in ('Type=', 'Restart=', 'RestartSec=', 'WatchdogSec=', 'TimeoutStopSec=', 'TimeoutStartSec='):
                self.assertFalse(any(line.startswith(key) for line in text.splitlines()), key)

    def test_required_hooks_restore_before_a_simulated_restart(self):
        import configparser
        import shlex
        from test_session import FakeHost, module
        unit = configparser.ConfigParser(interpolation=None)
        unit.optionxform = str
        unit.read(HERE / 'pt31553.conf')
        service = unit['Service']
        helper = '/usr/lib/pt31553-fan-control/session '
        for key, command in [('ExecCondition', 'guard'), ('ExecStartPre', 'prepare-start'),
                             ('ExecStopPost', 'restore-auto')]:
            self.assertEqual(service[key], helper + command)
        self.assertEqual(service['TimeoutAbortSec'], '5')
        with tempfile.TemporaryDirectory() as state:
            host = FakeHost()
            session = module.Session(host, Path(state), {'channels': ['pwm1_enable', 'pwm2_enable']})
            def hook(key):
                return session.run(shlex.split(service[key])[1])
            # systemd: condition -> pre-start -> daemon -> post-stop -> restart condition.
            self.assertEqual(hook('ExecCondition'), 0)
            self.assertEqual(hook('ExecStartPre'), 0)
            host.modes = {'pwm1_enable': '1', 'pwm2_enable': '1'}
            self.assertEqual(hook('ExecStopPost'), 0)
            self.assertEqual(host.modes, {'pwm1_enable': '2', 'pwm2_enable': '2'})
            self.assertEqual(hook('ExecCondition'), 0)
            self.assertEqual(hook('ExecStartPre'), 0)
            host.failed.add('pwm1_enable')
            self.assertEqual(hook('ExecStopPost'), 2)
            self.assertEqual(hook('ExecCondition'), 1)
            # Even cleanup after a skipped condition must preserve the fault.
            host.failed.clear()
            self.assertEqual(hook('ExecStopPost'), 0)
            self.assertEqual(hook('ExecCondition'), 1)
