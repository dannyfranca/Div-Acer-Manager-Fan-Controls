import importlib.util
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('session', Path(__file__).parent / 'session.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class StockBoot(unittest.TestCase):
    def test_stock_guard_skips_and_cleanup_does_not_touch_hardware(self):
        with tempfile.TemporaryDirectory() as root:
            class Host:
                boot_id = 'boot-a'
                def qualified_device(self, config):
                    return None
            session = module.Session(Host(), Path(root), {})
            self.assertEqual(session.run('guard'), 1)
            self.assertEqual(session.run('restore-auto'), 0)
            self.assertFalse((Path(root) / 'fault.json').exists())


class FakeHost:
    boot_id = 'boot-a'
    def __init__(self):
        self.device = '/sys/devices/platform/acer-wmi/hwmon/hwmon9'
        self.modes = {'pwm1_enable': '1', 'pwm2_enable': '1'}
        self.writes = []
        self.sensors_ok = True
        self.stopped = True
        self.failed = set()
        self.mismatch = set()
    def qualified_device(self, config):
        return self.device
    def write_auto(self, device, channel):
        self.writes.append(channel)
        if channel in self.failed:
            raise OSError('write failed')
        self.modes[channel] = '1' if channel in self.mismatch else '2'
    def read_mode(self, device, channel):
        return self.modes[channel]
    def fresh_sensors(self, config):
        if not self.sensors_ok:
            raise ValueError('stale sensor')
    def require_stopped(self):
        if not self.stopped:
            raise ValueError('controller active or job pending')

class Transitions(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.state = Path(self.temp.name)
        self.host = FakeHost()
        self.session = module.Session(self.host, self.state, {'channels': ['pwm1_enable', 'pwm2_enable']})
    def test_start_and_exit_restore_both_fans(self):
        self.assertEqual(self.session.run('prepare-start'), 0)
        self.assertEqual(self.host.modes, {'pwm1_enable': '2', 'pwm2_enable': '2'})
        self.host.modes = {'pwm1_enable': '1', 'pwm2_enable': '1'}
        self.assertEqual(self.session.run('restore-auto'), 0)
        self.assertEqual(self.host.modes, {'pwm1_enable': '2', 'pwm2_enable': '2'})
        self.assertFalse((self.state / 'owner.json').exists())
    def test_failed_first_fan_still_attempts_second_and_latches_until_recovery(self):
        self.session.run('prepare-start')
        self.host.writes.clear()
        self.host.failed.add('pwm1_enable')
        self.assertEqual(self.session.run('restore-auto'), 2)
        self.assertEqual(self.host.writes, ['pwm1_enable', 'pwm2_enable'])
        self.assertEqual(self.session.run('guard'), 1)
        self.host.failed.clear()
        self.assertEqual(self.session.run('restore-auto'), 0)
        self.assertEqual(self.session.run('guard'), 1)
        self.assertEqual(self.session.run('recover'), 0)
        self.assertEqual(self.session.run('guard'), 0)
    def test_timeout_on_each_fan_is_bounded_and_latched(self):
        import signal
        import time
        def slow_write(device, channel):
            self.host.writes.append(channel)
            time.sleep(3)
        self.host.write_auto = slow_write
        previous = signal.signal(signal.SIGALRM, module.deadline_expired)
        started = time.monotonic()
        try:
            signal.setitimer(signal.ITIMER_REAL, 0.02)
            self.assertEqual(self.session.run('prepare-start'), 2)
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, previous)
        self.assertLess(time.monotonic() - started, 2.5)
        self.assertEqual(self.host.writes, ['pwm1_enable', 'pwm2_enable'])
        self.assertTrue((self.state / 'fault.json').exists())

    def test_lost_device_after_ownership_is_fault(self):
        self.session.run('prepare-start')
        self.host.device = None
        self.assertEqual(self.session.run('restore-auto'), 2)
        self.assertTrue((self.state / 'owner.json').exists())
        self.assertEqual(self.session.run('recover'), 2)
    def test_stale_start_sensor_keeps_ownership_for_cleanup(self):
        self.host.sensors_ok = False
        self.assertEqual(self.session.run('prepare-start'), 2)
        self.assertTrue((self.state / 'owner.json').exists())
        self.assertEqual(self.session.run('restore-auto'), 0)
        self.assertEqual(self.session.run('guard'), 1)
    def test_readback_mismatch_is_not_success(self):
        self.host.mismatch.add('pwm1_enable')
        self.assertEqual(self.session.run('prepare-start'), 2)
        self.assertIn('pwm2_enable', self.host.writes)
    def test_recover_refuses_active_controller_and_preserves_fault(self):
        self.host.failed.add('pwm1_enable')
        self.session.run('prepare-start')
        self.host.failed.clear()
        self.host.stopped = False
        self.assertEqual(self.session.run('recover'), 2)
        self.assertEqual(self.session.run('guard'), 1)
    def test_sleep_marker_prevents_start_and_recovery(self):
        (self.state / 'sleep.json').write_text('{"boot_id":"boot-a"}')
        self.assertEqual(self.session.run('guard'), 1)
        self.assertEqual(self.session.run('prepare-start'), 2)
        self.assertEqual(self.session.run('recover'), 2)
        self.assertFalse(self.host.writes)
    def test_rediscovery_survives_hwmon_renumbering(self):
        self.session.run('prepare-start')
        self.host.device = '/sys/devices/platform/acer-wmi/hwmon/hwmon42'
        self.assertEqual(self.session.run('restore-auto'), 0)
    def test_changed_configuration_does_not_replace_owned_device_contract(self):
        self.session.run('prepare-start')
        self.session.config = {}
        self.assertEqual(self.session.run('restore-auto'), 0)

class LinuxBoundary(unittest.TestCase):
    def setUp(self):
        import hashlib
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        def write(path, value):
            target = self.root / path.lstrip('/')
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(value)
        write('/proc/sys/kernel/random/boot_id', 'boot-test')
        write('/proc/sys/kernel/osrelease', 'qualified-kernel')
        write('/sys/class/dmi/id/product_name', 'Predator PT315-53')
        write('/sys/class/dmi/id/board_name', 'Civic_TLS')
        write('/sys/module/acer_wmi/notes/.note.gnu.build-id', 'loaded-note')
        self.device = self.root / 'sys/devices/platform/acer-wmi'
        driver = self.root / 'sys/bus/platform/drivers/acer-wmi'
        driver.mkdir(parents=True)
        write('/sys/devices/platform/acer-wmi/hwmon/hwmon7/name', 'acer')
        (self.device / 'driver').symlink_to(driver)
        for channel in ('pwm1_enable', 'pwm2_enable'):
            write('/sys/devices/platform/acer-wmi/hwmon/hwmon7/' + channel, '1')
        self.config = dict(qualified=True, kernel_release='qualified-kernel',
                           module_note_sha256=hashlib.sha256(b'loaded-note').hexdigest(),
                           device_path='/sys/devices/platform/acer-wmi', hwmon_name='acer',
                           channels=['pwm1_enable', 'pwm2_enable'])
        self.host = module.LinuxHost(self.root)
    def test_loaded_identity_required_and_renumbering_allowed(self):
        self.assertIsNotNone(self.host.qualified_device(self.config))
        (self.device / 'hwmon/hwmon7').rename(self.device / 'hwmon/hwmon18')
        self.assertEqual(self.host.qualified_device(self.config).name, 'hwmon18')
        self.config['module_note_sha256'] = 'different'
        self.assertIsNone(self.host.qualified_device(self.config))
    def test_wrong_model_gets_no_writes(self):
        (self.root / 'sys/class/dmi/id/product_name').write_text('Another laptop')
        self.assertIsNone(self.host.qualified_device(self.config))
        self.assertEqual((self.device / 'hwmon/hwmon7/pwm1_enable').read_text(), '1')
    def test_missing_first_channel_does_not_prevent_second_restore(self):
        state = self.root / 'state'
        state.mkdir()
        self.host.fresh_sensors = lambda config: None
        session = module.Session(self.host, state, self.config)
        self.assertEqual(session.run('prepare-start'), 0)
        (self.device / 'hwmon/hwmon7/pwm1_enable').unlink()
        (self.device / 'hwmon/hwmon7/pwm2_enable').write_text('1')
        self.assertEqual(session.run('restore-auto'), 2)
        self.assertEqual((self.device / 'hwmon/hwmon7/pwm2_enable').read_text().strip(), '2')
    def test_pending_restart_refuses_recovery(self):
        self.host.execute = lambda *args, **kwargs: 'ActiveState=inactive\nSubState=dead\nJob=42\n'
        with self.assertRaises(ValueError):
            self.host.require_stopped()
    def test_cpu_and_gpu_are_read_from_selected_live_backends(self):
        cpu = self.root / 'sys/devices/platform/coretemp.0/hwmon/hwmon3'
        cpu.mkdir(parents=True)
        (cpu / 'name').write_text('coretemp')
        (cpu / 'temp1_label').write_text('Package id 0')
        (cpu / 'temp1_input').write_text('45000')
        self.config['cpu'] = dict(device_path='/sys/devices/platform/coretemp.0', label='Package id 0', min_c=1, max_c=99)
        self.config['gpu'] = dict(uuid='GPU-fixture', min_c=1, max_c=99)
        self.host.execute = lambda *args, **kwargs: 'GPU-fixture, 42\n'
        self.host.fresh_sensors(self.config)
        self.host.execute = lambda *args, **kwargs: 'GPU-fixture, [GPU requires reset]\n'
        with self.assertRaises(ValueError):
            self.host.fresh_sensors(self.config)
        self.host.execute = lambda *args, **kwargs: 'GPU-other, 42\n'
        with self.assertRaises(ValueError):
            self.host.fresh_sensors(self.config)
        self.host.execute = lambda *args, **kwargs: 'GPU-fixture, 42\n'
        self.config['cpu']['min_c'] = '0'
        state = self.root / 'state'
        state.mkdir()
        session = module.Session(self.host, state, self.config)
        self.assertEqual(session.run('prepare-start'), 2)
        self.assertTrue((state / 'fault.json').exists())
        self.config['cpu']['min_c'] = 1
        (cpu / 'temp1_fault').write_text('1')
        with self.assertRaises(ValueError):
            self.host.fresh_sensors(self.config)


if __name__ == '__main__':
    unittest.main()
