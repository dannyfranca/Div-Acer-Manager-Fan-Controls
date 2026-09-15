#!/usr/bin/python3
"""Finite CoolerControl ownership transitions; never a curve controller."""
import json
import subprocess
from pathlib import Path


class Session:
    def __init__(self, host, state, config):
        self.host, self.state, self.config = host, state, config
        self.config_source = None

    def load_config(self, command, path):
        import tomllib
        if command in ('restore-auto', 'finish-sleep'):
            return
        if command == 'prepare-sleep':
            self.config_source = path
            return
        owner = self.read_state('owner') if command == 'recover' else None
        if owner:
            self.config = owner['config']
        else:
            with path.open('rb') as source:
                self.config = tomllib.load(source)

    def read_state(self, name):
        path = self.state / (name + '.json')
        if not path.exists():
            return None
        value = json.loads(path.read_text())
        return value if value['boot_id'] == self.host.boot_id else None

    def write_state(self, name, **values):
        path = self.state / (name + '.json')
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps({'boot_id': self.host.boot_id, **values}))
        temporary.replace(path)

    def restore(self, config):
        device = self.host.qualified_device(config)
        if device is None:
            raise ValueError('qualified device missing during restoration')
        errors = []
        for channel in config['channels']:
            try:
                self.host.write_auto(device, channel)
                if self.host.read_mode(device, channel) != '2':
                    raise ValueError('Auto readback mismatch')
            except (OSError, ValueError) as error:
                errors.append(f'{channel}: {error}')
        if errors:
            raise ValueError('; '.join(errors))

    def run(self, command):
        try:
            return self.transition(command)
        except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
            if command in ('prepare-start', 'restore-auto', 'recover', 'prepare-sleep', 'finish-sleep'):
                self.write_state('fault', error=str(error))
            print(json.dumps({'command': command, 'error': str(error)}), flush=True)
            return 2

    def transition(self, command):
        if command in ('guard', 'prepare-start'):
            for latch in ('fault', 'sleep'):
                if self.read_state(latch):
                    print(json.dumps({'command': command, 'skip': latch + ' latch'}), flush=True)
                    return 1 if command == 'guard' else 2
        if command == 'guard':
            if self.host.qualified_device(self.config):
                return 0
            reason = ('owned device unavailable; restoration required' if self.read_state('owner')
                      else 'unsupported stock/recovery kernel; firmware retains ownership')
            print(json.dumps({'command': command, 'skip': reason}), flush=True)
            return 1
        if command == 'prepare-start':
            if self.host.qualified_device(self.config) is None:
                raise ValueError('unqualified device')
            previous = self.read_state('owner')
            if previous:
                self.restore(previous['config'])
            self.write_state('owner', config=self.config)
            self.restore(self.config)
            self.host.fresh_sensors(self.config)
            return 0
        if command == 'restore-auto':
            owner = self.read_state('owner')
            if owner:
                self.restore(owner['config'])
                (self.state / 'owner.json').unlink()
            return 0
        if command == 'recover':
            self.host.require_stopped()
            if self.read_state('sleep'):
                raise ValueError('sleep transition active')
            owner = self.read_state('owner')
            self.restore(owner['config'] if owner else self.config)
            (self.state / 'owner.json').unlink(missing_ok=True)
            (self.state / 'fault.json').unlink(missing_ok=True)
            return 0
        if command == 'prepare-sleep':
            if self.read_state('sleep'):
                raise ValueError('sleep transition already active')
            self.write_state('sleep', restart=False, prepared=False)
            active = self.host.controller_active()
            self.write_state('sleep', restart=active, prepared=False)
            owner = self.read_state('owner')
            if not active and not owner and not self.read_state('fault'):
                self.write_state('sleep', restart=False, prepared=True)
                print(json.dumps({'command': command, 'skip': 'clean unowned boot'}), flush=True)
                return 0
            if owner:
                contract = owner['config']
            else:
                if self.config_source:
                    self.load_config('prepare-start', self.config_source)
                contract = self.config
            stop_error = None
            try:
                self.host.stop_controller()
            except (OSError, ValueError, subprocess.SubprocessError) as error:
                stop_error = error
            try:
                self.host.require_stopped()
            except (OSError, ValueError, subprocess.SubprocessError) as error:
                stop_error = stop_error or error
                # Retry within the overall deadline; never race an active fan writer.
                try:
                    self.host.stop_controller()
                except (OSError, ValueError, subprocess.SubprocessError):
                    pass  # Actual stopped state below determines whether writes are safe.
                self.host.require_stopped()
            owner = self.read_state('owner')
            if not owner:
                self.write_state('owner', config=contract)
            self.restore(contract)
            if stop_error:
                raise ValueError('controller stop failed: ' + str(stop_error))
            if self.read_state('fault'):
                raise ValueError('restoration fault requires explicit recovery')
            (self.state / 'owner.json').unlink(missing_ok=True)
            self.write_state('sleep', restart=active, prepared=True)
            return 0
        if command == 'finish-sleep':
            sleep = self.read_state('sleep')
            if not sleep:
                return 0
            (self.state / 'sleep.json').unlink()
            if sleep['prepared'] and sleep['restart'] and not self.read_state('fault'):
                self.host.start_controller()
            return 0
        raise ValueError('unknown command')


class LinuxHost:
    """OS boundary; fixtures substitute this or supply a disposable sysfs tree."""
    def __init__(self, root=Path('/'), execute=None):
        import subprocess
        self.lock = None
        self.pending_start = False
        self.root = root
        self.execute = execute or subprocess.check_output
        self.boot_id = self.text('/proc/sys/kernel/random/boot_id')

    def path(self, path):
        return self.root / str(path).lstrip('/')

    def text(self, path):
        return self.path(path).read_text().strip()

    def qualified_device(self, config):
        import hashlib
        try:
            if not config.get('qualified', False):
                return None
            if self.text('/sys/class/dmi/id/product_name') != 'Predator PT315-53':
                return None
            if self.text('/sys/class/dmi/id/board_name') != 'Civic_TLS':
                return None
            if self.text('/proc/sys/kernel/osrelease') != config['kernel_release']:
                return None
            note = self.path('/sys/module/acer_wmi/notes/.note.gnu.build-id').read_bytes()
            if hashlib.sha256(note).hexdigest() != config['module_note_sha256']:
                return None
            if config['channels'] != ['pwm1_enable', 'pwm2_enable']:
                return None
            device = self.path(config['device_path']).resolve(strict=True)
            if not device.is_relative_to(self.path('/sys/devices').resolve()):
                return None
            driver = (device / 'driver').resolve(strict=True)
            if driver != self.path('/sys/bus/platform/drivers/acer-wmi').resolve(strict=True):
                return None
            matches = [p for p in (device / 'hwmon').glob('hwmon*')
                       if (p / 'name').read_text().strip() == config['hwmon_name']]
            return matches[0] if len(matches) == 1 else None
        except (OSError, KeyError, ValueError):
            return None

    def write_auto(self, device, channel):
        # Never create a missing endpoint as an ordinary file.
        import os
        fd = os.open(device / channel, os.O_WRONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, 'w') as target:
            target.write('2\n')

    def read_mode(self, device, channel):
        return (device / channel).read_text().strip()

    def fresh_sensors(self, config):
        import math
        import time
        started = time.monotonic()
        for sensor in (config['cpu'], config['gpu']):
            bounds = (sensor['min_c'], sensor['max_c'])
            if (any(type(bound) not in (int, float) or not math.isfinite(bound) for bound in bounds)
                    or bounds[0] > bounds[1]):
                raise ValueError('invalid sensor bounds')
        cpu = config['cpu']
        parent = self.path(cpu['device_path']).resolve(strict=True)
        if not parent.is_relative_to(self.path('/sys/devices').resolve()):
            raise ValueError('invalid CPU device path')
        values = []
        for hwmon in (parent / 'hwmon').glob('hwmon*'):
            if (hwmon / 'name').read_text().strip() != 'coretemp':
                continue
            for label in hwmon.glob('temp*_label'):
                if label.read_text().strip() == cpu['label']:
                    source = label.with_name(label.name.replace('_label', '_input'))
                    fault = label.with_name(label.name.replace('_label', '_fault'))
                    if fault.exists() and fault.read_text().strip() != '0':
                        raise ValueError('CPU sensor fault')
                    values.append(float(source.read_text()) / 1000)
        if len(values) != 1:
            raise ValueError('selected CPU sensor missing or ambiguous')
        gpu = config['gpu']
        output = self.execute(['/usr/bin/nvidia-smi', '--id=' + gpu['uuid'],
                               '--query-gpu=uuid,temperature.gpu', '--format=csv,noheader,nounits'],
                              text=True, timeout=3)
        rows = [line.split(',') for line in output.strip().splitlines()]
        if len(rows) != 1 or len(rows[0]) != 2 or rows[0][0].strip() != gpu['uuid']:
            raise ValueError('selected GPU sensor missing or ambiguous')
        values.append(float(rows[0][1]))
        for value, sensor in zip(values, (cpu, gpu)):
            if not math.isfinite(value) or not sensor['min_c'] <= value <= sensor['max_c']:
                raise ValueError('invalid selected sensor reading')
        # Read directly from the selected backends for this invocation, never a cached file.
        if time.monotonic() - started > 4:
            raise ValueError('sensor acquisition expired')

    def controller_active(self):
        output = self.execute(['/usr/bin/systemctl', 'show', 'coolercontrold.service',
                               '--property=ActiveState,SubState,Job'], text=True, timeout=3)
        fields = dict(line.split('=', 1) for line in output.splitlines() if '=' in line)
        active = fields.get('ActiveState')
        if active not in ('active', 'reloading', 'activating', 'deactivating', 'inactive', 'failed'):
            raise ValueError('controller state unavailable')
        # Pending/partial transitions must be stopped too; never treat them as a clean skip.
        return active not in ('inactive', 'failed') or fields.get('Job') not in ('', '0')

    def stop_controller(self):
        import fcntl
        # ExecStopPost takes this same lock. The persistent sleep latch excludes new starts.
        fcntl.flock(self.lock, fcntl.LOCK_UN)
        try:
            self.execute(['/usr/bin/systemctl', 'stop', 'coolercontrold.service'],
                         text=True, timeout=25)
        finally:
            fcntl.flock(self.lock, fcntl.LOCK_EX)

    def start_controller(self):
        # main queues this only after releasing the lock, so ExecCondition can acquire it.
        self.pending_start = True

    def flush_start(self):
        if self.pending_start:
            self.execute(['/usr/bin/systemctl', '--no-block', 'start', 'coolercontrold.service'],
                         text=True, timeout=3)

    def require_stopped(self):
        output = self.execute(['/usr/bin/systemctl', 'show', 'coolercontrold.service',
                               '--property=ActiveState,SubState,Job'], text=True, timeout=3)
        fields = dict(line.split('=', 1) for line in output.splitlines() if '=' in line)
        if (fields.get('ActiveState') not in ('inactive', 'failed')
                or fields.get('SubState') not in ('dead', 'failed')
                or fields.get('Job') not in ('', '0')):
            raise ValueError('controller not fully stopped or has pending job')


def deadline_expired(signum, frame):
    import signal
    # Restore catches the first timeout to attempt fan two; it still needs a deadline.
    signal.alarm(1)
    raise TimeoutError('transition deadline exceeded')


def main():
    import argparse
    import fcntl
    import os
    import signal
    import subprocess
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['guard', 'prepare-start', 'restore-auto', 'recover',
                                                   'prepare-sleep', 'finish-sleep'])
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error('requires root')
    os.umask(0o077)
    state = Path('/run/pt31553-fan-control')
    state.mkdir(mode=0o700, exist_ok=True)
    # One bounded transaction, shared by systemd hooks and explicit recovery.
    with (state / 'lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print('another transition is active', flush=True)
            return 2
        host = LinuxHost()
        host.lock = lock
        session = Session(host, state, {})
        signal.signal(signal.SIGALRM, deadline_expired)
        signal.alarm(35 if args.command == 'prepare-sleep' else 8)
        try:
            # Cleanup uses the owned contract even if live configuration was removed/broken.
            session.load_config(args.command, Path('/etc/pt31553-fan-control/device.toml'))
            result = session.run(args.command)
            print(json.dumps({'command': args.command, 'result': result}), flush=True)
        except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
            if args.command != 'guard':
                session.write_state('fault', error=str(error))
            print(json.dumps({'command': args.command, 'error': str(error)}), flush=True)
            return 2
        finally:
            signal.alarm(0)
    try:
        host.flush_start()
    except (OSError, subprocess.SubprocessError) as error:
        with (state / 'lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            session.write_state('fault', error=str(error))
        print(json.dumps({'command': args.command, 'error': str(error)}), flush=True)
        return 2
    return result


if __name__ == '__main__':
    raise SystemExit(main())
