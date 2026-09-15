"""Sleep lifecycle fixtures; no system service or physical fan is touched."""
from pathlib import Path
import tempfile
import unittest
from test_session import FakeHost, module

ENGINES = ('suspend', 'hibernate', 'hybrid-sleep', 'suspend-then-hibernate')

class SleepHost(FakeHost):
    def __init__(self):
        super().__init__()
        self.active = True
        self.queued_starts = 0
        self.stops = 0
    def controller_active(self):
        return self.active
    def stop_controller(self):
        self.stops += 1
        self.active = False
        self.session.run('restore-auto')
    def start_controller(self):
        self.queued_starts += 1
    def require_stopped(self):
        if self.active:
            raise ValueError('still active')

class SleepTransitions(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.state = Path(self.temp.name)
        self.host = SleepHost()
        self.session = module.Session(self.host, self.state, {'channels': ['pwm1_enable', 'pwm2_enable']})
        self.host.session = self.session
    def test_active_controller_relinquishes_before_sleep_and_resumes_once(self):
        self.session.run('prepare-start')
        self.host.modes = {'pwm1_enable': '1', 'pwm2_enable': '1'}
        self.assertEqual(self.session.run('prepare-sleep'), 0)
        self.assertFalse(self.host.active)
        self.assertEqual(self.host.modes, {'pwm1_enable': '2', 'pwm2_enable': '2'})
        self.assertEqual(self.session.run('guard'), 1)
        self.assertEqual(self.session.run('finish-sleep'), 0)
        self.assertEqual(self.session.run('finish-sleep'), 0)
        self.assertEqual(self.host.queued_starts, 1)
        self.assertFalse((self.state / 'sleep.json').exists())
    def test_clean_stock_sleep_never_writes_or_starts_controller(self):
        self.host.device = None
        self.host.active = False
        self.assertEqual(self.session.run('prepare-sleep'), 0)
        self.assertEqual(self.session.run('finish-sleep'), 0)
        self.assertEqual(self.host.writes, [])
        self.assertEqual(self.host.stops, 0)
        self.assertEqual(self.host.queued_starts, 0)
        self.assertFalse((self.state / 'fault.json').exists())

class EngineLifecycle(unittest.TestCase):
    def test_all_engines_gate_sleep_and_cleanup_every_outcome(self):
        import configparser
        here = Path(__file__).parent
        unit = configparser.ConfigParser()
        unit.read(here / 'pt31553-fan-sleep.service')
        prepare = unit['Service']['ExecStart'].split()[-1]
        finish = unit['Service']['ExecStopPost'].split()[-1]
        for engine in ENGINES:
            for scenario in ('active', 'inactive', 'stock', 'lts', 'lost-owner', 'fault',
                             'mismatch', 'stop-failed', 'sensor-lost'):
                with self.subTest(engine=engine, scenario=scenario), tempfile.TemporaryDirectory() as tmp:
                    host = SleepHost()
                    session = module.Session(host, Path(tmp), {'channels': ['pwm1_enable', 'pwm2_enable']})
                    host.session = session
                    if scenario in ('stock', 'lts'):
                        host.device = None
                        host.active = False
                    elif scenario == 'inactive':
                        host.active = False
                        host.modes = {'pwm1_enable': '2', 'pwm2_enable': '2'}
                    else:
                        self.assertEqual(session.run('prepare-start'), 0)
                    host.writes.clear()
                    if scenario == 'lost-owner':
                        host.device = None
                    if scenario == 'fault':
                        session.write_state('fault', error='previous restoration failed')
                    if scenario == 'mismatch':
                        host.mismatch.add('pwm1_enable')
                    if scenario == 'stop-failed':
                        host.stop_controller = lambda: None
                    blocked = scenario in ('lost-owner', 'fault', 'mismatch', 'stop-failed')
                    self.assertEqual(session.run(prepare), 2 if blocked else 0)
                    # Requires+After prevents the engine from running when preparation fails.
                    if not blocked and scenario not in ('stock', 'lts'):
                        self.assertFalse(host.active)
                        self.assertEqual(set(host.modes.values()), {'2'})
                    self.assertEqual(session.run(finish), 0)
                    self.assertFalse((Path(tmp) / 'sleep.json').exists())
                    expected_restart = not blocked and scenario not in ('stock', 'lts', 'inactive')
                    self.assertEqual(host.queued_starts, int(expected_restart))
                    self.assertEqual(bool(session.read_state('fault')), blocked)
                    if scenario in ('stock', 'lts'):
                        self.assertEqual(host.writes, [])
                    if expected_restart:
                        if scenario == 'sensor-lost':
                            host.sensors_ok = False
                        self.assertEqual(session.run('guard'), 0)
                        self.assertEqual(session.run('prepare-start'), 2 if scenario == 'sensor-lost' else 0)
                    self.assertEqual(session.run(finish), 0)
                    self.assertEqual(host.queued_starts, int(expected_restart))

    def test_sleep_units_validate_and_package_all_four_required_dependencies(self):
        import configparser
        import os
        import subprocess
        here = Path(__file__).parent
        drop = configparser.ConfigParser()
        drop.read(here / 'sleep-engine.conf')
        self.assertEqual(drop['Unit']['Requires'], 'pt31553-fan-sleep.service')
        self.assertEqual(drop['Unit']['After'], 'pt31553-fan-sleep.service')
        unit = configparser.ConfigParser()
        unit.read(here / 'pt31553-fan-sleep.service')
        self.assertEqual(unit['Unit']['StopWhenUnneeded'], 'yes')
        self.assertEqual(unit['Service']['RemainAfterExit'], 'yes')
        self.assertEqual(unit['Service']['Type'], 'oneshot')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # Execute only package() into a disposable root. No build/install/service actions.
            build = here / 'PKGBUILD'
            if not build.exists():
                build = here.parent / 'PKGBUILD'
            subprocess.run(['bash', '-c', 'source "$1"; package', 'package-fixture', str(build.resolve())], cwd=here,
                           env={**os.environ, 'pkgdir': str(root)}, check=True)
            units = root / 'usr/lib/systemd/system'
            sleep_unit = units / 'pt31553-fan-sleep.service'
            sleep_unit.write_text(sleep_unit.read_text().replace('/usr/lib/pt31553-fan-control/session', '/usr/bin/true'))
            targets = [str(sleep_unit)]
            for engine in ENGINES:
                name = 'systemd-' + engine + '.service'
                self.assertEqual((units / (name + '.d/pt31553.conf')).read_text(), (here / 'sleep-engine.conf').read_text())
                # Use real engine semantics with an inert executable; never invoke sleep.
                source = Path('/usr/lib/systemd/system') / name
                text = source.read_text().replace('/usr/lib/systemd/systemd-sleep', '/usr/bin/true')
                (units / name).write_text(text)
                targets.append(str(units / name))
            result = subprocess.run(['systemd-analyze', 'verify', '--man=no', *targets],
                                    env={**os.environ, 'SYSTEMD_UNIT_PATH': str(units) + ':/usr/lib/systemd/system'},
                                    text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_stop_releases_mutex_for_post_stop_and_resume_is_deferred(self):
        import fcntl
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            boot = root / 'proc/sys/kernel/random/boot_id'
            boot.parent.mkdir(parents=True)
            boot.write_text('fixture')
            calls = []
            with (root / 'lock').open('a') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                def execute(args, **kwargs):
                    with (root / 'lock').open('a') as hook_lock:
                        fcntl.flock(hook_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    calls.append(args)
                    return ''
                host = module.LinuxHost(root, execute)
                host.lock = lock
                host.stop_controller()
                host.start_controller()
                self.assertEqual(len(calls), 1)
                with (root / 'lock').open('a') as other:
                    with self.assertRaises(BlockingIOError):
                        fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
            host.flush_start()
            self.assertEqual(calls[-1][1:3], ['--no-block', 'start'])

    def test_failed_stop_still_restores_when_stopped_and_retries_when_active(self):
        import subprocess
        for stopped_on_error, retry_error in ((True, False), (False, False), (False, True)):
            with self.subTest(stopped=stopped_on_error, retry_error=retry_error), tempfile.TemporaryDirectory() as tmp:
                host = SleepHost()
                session = module.Session(host, Path(tmp), {'channels': ['pwm1_enable', 'pwm2_enable']})
                host.session = session
                self.assertEqual(session.run('prepare-start'), 0)
                host.modes = {'pwm1_enable': '1', 'pwm2_enable': '1'}
                calls = []
                def stop():
                    calls.append(1)
                    host.active = not stopped_on_error and len(calls) == 1
                    if len(calls) == 1 or retry_error:
                        raise subprocess.CalledProcessError(1, 'systemctl')
                host.stop_controller = stop
                self.assertEqual(session.run('prepare-sleep'), 2)
                self.assertFalse(host.active)
                self.assertEqual(set(host.modes.values()), {'2'})
                self.assertEqual(len(calls), 1 if stopped_on_error else 2)
                self.assertEqual(session.run('finish-sleep'), 0)
                self.assertEqual(host.queued_starts, 0)
                self.assertTrue(session.read_state('fault'))

    def test_owned_sleep_restoration_survives_deleted_or_broken_configuration(self):
        for contents in (None, 'invalid TOML !'):
            with self.subTest(contents=contents), tempfile.TemporaryDirectory() as tmp:
                host = SleepHost()
                session = module.Session(host, Path(tmp), {'channels': ['pwm1_enable', 'pwm2_enable']})
                host.session = session
                self.assertEqual(session.run('prepare-start'), 0)
                source = Path(tmp) / 'device.toml'
                if contents:
                    source.write_text(contents)
                session.config = {}
                session.load_config('prepare-sleep', source)
                self.assertEqual(session.run('prepare-sleep'), 0)
                self.assertFalse(host.active)
                self.assertEqual(set(host.modes.values()), {'2'})

    def test_engine_lifecycle_cleans_up_on_success_cancel_and_execution_failure(self):
        for engine in ENGINES:
            for outcome in ('success', 'cancel-before-engine', 'cancel-running', 'exec-failure', 'prepare-failure'):
                with self.subTest(engine=engine, outcome=outcome), tempfile.TemporaryDirectory() as tmp:
                    host = SleepHost()
                    session = module.Session(host, Path(tmp), {'channels': ['pwm1_enable', 'pwm2_enable']})
                    host.session = session
                    session.run('prepare-start')
                    if outcome == 'prepare-failure':
                        host.mismatch.add('pwm1_enable')
                    lifecycle = SleepUnitLifecycle(engine, session)
                    lifecycle.submit()
                    self.assertIsNotNone(session.read_state('sleep'))
                    if outcome != 'prepare-failure':
                        self.assertFalse(host.active)
                        self.assertEqual(set(host.modes.values()), {'2'})
                    if outcome == 'cancel-before-engine':
                        lifecycle.cancel()
                    elif lifecycle.prepared:
                        lifecycle.execute_engine()
                        if outcome == 'cancel-running':
                            lifecycle.cancel()
                        else:
                            lifecycle.complete(exit_code=1 if outcome == 'exec-failure' else 0)
                    else:
                        lifecycle.fail_dependency()
                    self.assertFalse(session.read_state('sleep'))
                    self.assertEqual(lifecycle.events.count('finish-sleep'), 1)
                    self.assertEqual(host.queued_starts, 0 if outcome == 'prepare-failure' else 1)
                    self.assertEqual(bool(session.read_state('fault')), outcome == 'prepare-failure')
                    if outcome in ('prepare-failure', 'cancel-before-engine'):
                        self.assertNotIn('engine-start', lifecycle.events)
                    else:
                        self.assertLess(lifecycle.events.index('prepare-sleep'), lifecycle.events.index('engine-start'))
                    self.assertEqual(lifecycle.events[-1], 'finish-sleep')

    def test_faulted_sleep_preserves_contract_for_recovery_with_broken_live_config(self):
        import subprocess
        for prior_fault in (True, False):
            with self.subTest(prior_fault=prior_fault), tempfile.TemporaryDirectory() as tmp:
                host = SleepHost()
                contract = {'channels': ['pwm1_enable', 'pwm2_enable']}
                session = module.Session(host, Path(tmp), contract)
                host.session = session
                session.run('prepare-start')
                if prior_fault:
                    session.write_state('fault', error='existing fault')
                else:
                    def stop():
                        host.active = False
                        raise subprocess.CalledProcessError(1, 'systemctl')
                    host.stop_controller = stop
                self.assertEqual(session.run('prepare-sleep'), 2)
                self.assertEqual(session.read_state('owner')['config'], contract)
                self.assertEqual(session.run('finish-sleep'), 0)
                source = Path(tmp) / 'device.toml'
                source.write_text('broken TOML !')
                session.config = {}
                session.load_config('recover', source)
                self.assertEqual(session.run('recover'), 0)
                self.assertFalse(session.read_state('owner'))
                self.assertFalse(session.read_state('fault'))

    def test_clean_unowned_boot_needs_neither_config_nor_device_probe(self):
        for contents in (None, 'broken TOML !'):
            with self.subTest(contents=contents), tempfile.TemporaryDirectory() as tmp:
                host = SleepHost()
                host.active = False
                def forbidden(config):
                    raise AssertionError('clean boot probed fan device')
                host.qualified_device = forbidden
                session = module.Session(host, Path(tmp), {})
                source = Path(tmp) / 'device.toml'
                if contents:
                    source.write_text(contents)
                # Exercise the same config-loading boundary as the root CLI.
                session.load_config('prepare-sleep', source)
                self.assertEqual(session.run('prepare-sleep'), 0)
                self.assertEqual(session.run('finish-sleep'), 0)
                self.assertFalse(host.writes)
                self.assertEqual(host.queued_starts, 0)
                self.assertFalse(session.read_state('fault'))


class SleepUnitLifecycle:
    """Small dependency/job fixture driven by deployed unit directives; no real sleep."""
    def __init__(self, engine, session):
        import configparser
        self.engine, self.session = engine, session
        self.unit = configparser.ConfigParser()
        self.unit.read(Path(__file__).parent / 'pt31553-fan-sleep.service')
        self.drop = configparser.ConfigParser()
        self.drop.read(Path(__file__).parent / 'sleep-engine.conf')
        self.events = []
        self.consumer = None
        self.helper_active = False
        self.prepared = False

    def hook(self, directive):
        command = self.unit['Service'][directive].split()[-1]
        self.events.append(command)
        return self.session.run(command)

    def submit(self):
        self.consumer = 'queued'
        if ('pt31553-fan-sleep.service' in self.drop['Unit']['Requires'].split()
                and 'pt31553-fan-sleep.service' in self.drop['Unit']['After'].split()):
            self.prepared = self.hook('ExecStart') == 0
            self.helper_active = self.prepared and self.unit['Service'].getboolean('RemainAfterExit')

    def execute_engine(self):
        if not self.prepared:
            raise AssertionError('engine cannot execute before required preparation')
        self.consumer = 'running'
        self.events.append('engine-start')

    def cancel(self):
        self.events.append('cancel-' + self.consumer)
        self.retire()

    def complete(self, exit_code):
        assert self.consumer == 'running'
        self.events.append('engine-failed' if exit_code else 'engine-completed')
        self.retire()

    def fail_dependency(self):
        assert not self.prepared
        self.events.append('dependency-failed')
        self.retire()

    def retire(self):
        self.consumer = None
        if not self.prepared or (self.helper_active and self.unit['Unit'].getboolean('StopWhenUnneeded')):
            self.hook('ExecStopPost')
            self.helper_active = False
