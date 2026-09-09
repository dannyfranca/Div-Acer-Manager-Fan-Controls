# Smallest adaptation for temperature-based PT315-53 fan control

Research date: 2026-09-09. Planning only; no module built, loaded, installed, or hardware control written.

## Decision

Prefer investigating **the existing exact-model `acer_wmi` patches plus an established hwmon curve controller**. A replacement module built for the running kernel is a plausible smaller delivery route than rebuilding the entire kernel. The patches are mechanically applicable today, but their firmware assumptions remain untested. Do not treat this as demonstrated PT315-53 support.

This DAM fork already has temperature-based control, but using it reliably requires driver protocol verification, an Auto-restoration implementation, and several daemon corrections. Changing its model name or slider range is insufficient. Reusing the earlier project's small kernel change is more promising than carrying either project's full application stack.

## Exact evidence and limits

- The parent session's [machine observation](../wayfinder/pt31553/assets/machine-observation.json) records `Predator PT315-53`, `Civic_TLS`, BIOS `V1.17`, kernel `7.2.2-1-cachyos`, loaded `acer_wmi`, a present but unbound gaming WMI GUID, and no fan/PWM attributes in any hwmon device. The current kernel build directory exists. This does not establish firmware command compatibility.
- The old [telemetry patch](https://github.com/dannyfranca/predator-pt315-53-fan-control/blob/61682647b816ae080ee6f08c4b716e5849bfe8b3/packaging/kernel/patches/0001-acer-wmi-add-pt31553-telemetry.patch) adds exact Acer/product/board matching and `.predator_v4 = 1`. Its [second patch](https://github.com/dannyfranca/predator-pt315-53-fan-control/blob/61682647b816ae080ee6f08c4b716e5849bfe8b3/packaging/kernel/patches/0002-acer-wmi-enable-pt31553-pwm.patch) adds `.pwm = 1`. The [old source lock](https://github.com/dannyfranca/predator-pt315-53-fan-control/blob/61682647b816ae080ee6f08c4b716e5849bfe8b3/packaging/kernel/source-lock.toml) pins 7.1.8; its README explicitly says the hardware is unqualified.
- Retrieved [current CachyOS source](https://github.com/CachyOS/linux/blob/11f0a985180e84707198334e5e612c24fa947f9c/drivers/platform/x86/acer-wmi.c) (`cachyos-7.2.2-1`) and [old pinned source](https://github.com/CachyOS/linux/blob/7a84732fd5e4350c1312fd0ed0c72ffa139fb766/drivers/platform/x86/acer-wmi.c) are byte-identical: SHA-256 `8e3cd3cb8ac24cd387e5d24c69bd47e1b5868ac091d1f83958a3e36273c40f83`. Both patches pass sequential `git apply --check` against a disposable copy of that file. This verifies patch fit, not installed module identity, compilation, or hardware.

## What the existing Linux backend supplies

The code already implements fan tachometers, PWM, firmware mode reads/writes, firmware status validation, and supported-sensor discovery. Hardware support flags must actually advertise the fan sensors before their attributes appear. `pwm1/2` use 0–255; firmware commands use percent. `pwm*_enable=1` selects software-controlled duty, `2` restores firmware Auto, and `0` selects Turbo. These sysfs values differ from raw firmware enums: Custom is firmware `3`, Auto firmware `1`, Turbo firmware `2`. Do not write raw enum `3` to `pwm*_enable`; CoolerControl's ordinary sysfs `1/2` behavior matches this driver. A userspace temperature curve uses the driver's custom mode internally; the user does not adjust fans manually. [hwmon implementation](https://github.com/CachyOS/linux/blob/11f0a985180e84707198334e5e612c24fa947f9c/drivers/platform/x86/acer-wmi.c#L2910)

Two caveats matter. `.predator_v4` also enables platform-profile support; this first patch is not strictly limited to telemetry exposure, and profile registration occurs before hwmon registration. Also, current suspend/remove/shutdown callbacks do not restore fan Auto. Lifecycle recovery must be provided and verified by the controller/service. [capability selection](https://github.com/CachyOS/linux/blob/11f0a985180e84707198334e5e612c24fa947f9c/drivers/platform/x86/acer-wmi.c#L412), [platform lifecycle](https://github.com/CachyOS/linux/blob/11f0a985180e84707198334e5e612c24fa947f9c/drivers/platform/x86/acer-wmi.c#L2768)

## DAM fork: reusable curve, substantial remaining work

Inspected local revision `ffc43cf8acd442e7a3406c01ca81391a170c318c`. The PyInstaller [spec](https://github.com/dannyfranca/Div-Acer-Manager-Fan-Controls/blob/ffc43cf8acd442e7a3406c01ca81391a170c318c/DAM-FC/Daemon/DAMFC_daemon.spec) selects `DAMFC_daemon.py`; the similarly named second daemon is not the selected source.

| Area | Confirmed behavior | Implication |
|---|---|---|
| Temperature loop | Every five seconds, uses max(CPU, GPU), selects highest satisfied threshold, writes both fans | Already meets the basic temperature-driven requirement |
| Sensors | First `coretemp` reading through psutil; NVIDIA temperature through `nvidia-smi` | Verify package sensor identity and GPU availability; GPU subprocess has no timeout |
| Sensor failure | Converts missing/error temperatures to zero | A missing hot sensor can lower demand; failure must trigger recovery |
| Curve limits | No update below first threshold; no hysteresis; top step is used indefinitely | Explicit lower/upper behavior and stable down-ramping needed |
| Errors | Fan write exceptions logged and swallowed; uncaught curve errors can kill only control thread | Main socket process can survive without effective cooling control |
| Disabled dynamic mode | Sleep is inside the enabled branch | Disabled mode busy-loops |
| Exit | SIGTERM/SIGINT stop process without restoring Auto | Service stop/crash/suspend handling must restore firmware control |

Sources: [daemon](https://github.com/dannyfranca/Div-Acer-Manager-Fan-Controls/blob/ffc43cf8acd442e7a3406c01ca81391a170c318c/DAM-FC/Daemon/DAMFC_daemon.py), [sensor helpers](https://github.com/dannyfranca/Div-Acer-Manager-Fan-Controls/blob/ffc43cf8acd442e7a3406c01ca81391a170c318c/DAM-FC/Daemon/HardwareStatus.py). The GUI/configuration could be reused, but no UI rewrite is necessary to resolve device support.

The [DAM driver](https://github.com/dannyfranca/Div-Acer-Manager-Fan-Controls/blob/ffc43cf8acd442e7a3406c01ca81391a170c318c/DAM-FC/Daemon/NitroDrivers/acer_nitro_gaming_driver2.c) is more than a transport shim:

- Probe immediately sends two fan "unlock" commands, sets both speeds to 512, and changes keyboard lighting. No exact-model gate exists.
- It writes method 16 with decimal concatenation: `10 * slider_value + fan_id`, IDs 1/4. With multiples of 128, this happens to equal the current upstream speed layout: slider 640 → 25%, 1280 → 50%, 2560 → 100%. These are inferred protocol percentages, **not RPM**. Arbitrary slider values can corrupt the low-byte fan identifier; the driver does not validate that constraint.
- The [header](https://github.com/dannyfranca/Div-Acer-Manager-Fan-Controls/blob/ffc43cf8acd442e7a3406c01ca81391a170c318c/DAM-FC/Daemon/NitroDrivers/acer_nitro_gaming_driver2.h) supplies unlock values 7681 and 1638410. These differ from current upstream's explicit fan-bitmap/mode encoding. Shared GUID/method numbers do not establish the validity of these older commands on this machine.
- ACPI/firmware success is not reliably propagated to userspace; there is no mode readback, Auto operation, tachometer ABI, or automatic restoration on removal.

Consequently, making this fork dependable requires fixing the backend and the runtime—not merely tuning its existing curve. Upstream's [typed fan commands](https://github.com/CachyOS/linux/blob/11f0a985180e84707198334e5e612c24fa947f9c/drivers/platform/x86/acer-wmi.c#L1668) offer a clearer basis for the hardware experiment.

## Minimum implementation if the hardware check succeeds

1. Package the narrow exact-model quirk against the installed kernel source as a replacement `acer_wmi` module, preferably with update/rebuild integration after verification. First prove compilation against current headers. External-module kbuild supports this without a new kernel image; it requires the matching build configuration and symbols. Do not replace the entire kernel/NVIDIA package set solely because the earlier project chose that packaging model. [Linux external-module documentation](https://docs.kernel.org/kbuild/modules.html)
2. Configure an existing controller capable of ordinary hwmon PWM and CPU/GPU-based curves; evaluate CoolerControl first in the companion existing-support research. Its exact stop/failure/resume behavior must be checked before accepting it. Keep one owner of the fan controls.
3. Supply only missing recovery behavior: bounded/fresh sensor reads, errors that reach supervision, firmware Auto for both fans on stop/failure and before sleep, sensor re-discovery and fresh curve evaluation on resume. An independent stop helper is useful if the controller itself cannot recover after a crash.

The old [service](https://github.com/dannyfranca/predator-pt315-53-fan-control/blob/61682647b816ae080ee6f08c4b716e5849bfe8b3/systemd/pt31553-fand.service), [sleep guard](https://github.com/dannyfranca/predator-pt315-53-fan-control/blob/61682647b816ae080ee6f08c4b716e5849bfe8b3/systemd/pt31553-fan-sleep-guard.service), and [curve settings](https://github.com/dannyfranca/predator-pt315-53-fan-control/blob/61682647b816ae080ee6f08c4b716e5849bfe8b3/config/example.toml) are useful design references. Their signing/provenance/qualification machinery is not an inherent requirement of a separate, simpler solution. This proposal does not remove the old application's own admission gates or imply its executable can presently be enabled.

## Shortest staged hardware verification, for a later execution session

1. **Build without loading:** use the matching kernel source/headers and exact DMI patch; preserve stock module/kernel recovery. Inspect signing requirements and module replacement mechanics. First-stage code should expose telemetry without selecting custom fan mode; account for the coupled profile feature.
2. **Telemetry stage:** boot/load the reviewed candidate deliberately. Require both CPU/GPU tachometers and sensible readings; compare temperatures with coretemp/NVIDIA independently. A successful module load or visible GUID is insufficient. If discovery fails, investigate firmware methods before enabling PWM.
3. **Control stage:** add PWM capability, first verify mode and duty reads. During a short supervised test, establish Auto restoration, then confirm distinct moderate-to-high duties change the intended fan's RPM, and restore Auto after each test. Stop on a missing readback or incorrect response. These manual test points are verification steps; the delivered behavior remains automatic curves.
4. **Curve stage:** configure temperature-driven demand, verify CPU-only and GPU-only temperature response, then stop, failure, suspend/resume, and reboot behavior. Finish only when both fans respond to temperature and reliably return to firmware ownership when the controller stops.

The unresolved fact is whether PT315-53 BIOS 1.17 implements the assumed telemetry and PWM protocol. If it does, the remaining scope can be small. If it does not, this becomes firmware-interface research; no slider setting, daemon choice, or clean build resolves that mismatch.
