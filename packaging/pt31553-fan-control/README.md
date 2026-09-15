# PT315-53 CoolerControl transitions

Implements issue #12. No installation or hardware qualification is implied by the fixture results.
This is a finite Python helper, not a replacement curve controller. The default
configuration refuses startup. Sleep integration is tracked separately in #13;
do not enable live curves until that dependency and attended acceptance pass.

## Build and verification

Run `python3 -m unittest discover -s . -v` here, then `makepkg`.
The package neither enables nor starts CoolerControl. Install only with it stopped,
after the baseline and driver checks. Pacman's normal unit reload does not activate
control. The drop-in adds condition/start/stop hooks and `TimeoutAbortSec=5`, preserving
the inspected upstream notify, 30-second watchdog, restart and stop behavior.
The unit fixture was extracted from the published CachyOS 5.0.0-1 package
(SHA-256 `f6dcefb7e3ad9071d0bc0c28e3784bc0f5d5f8ddd1fd83fdeb692a9a32eb686d`).
`systemd-analyze verify` parses that unit with our drop-in using inert executable
substitutions; this validates units without running a daemon or touching hardware.
The package pins `coolercontrold=5.0.0-1` so an ordinary upgrade cannot silently
replace the audited unit. Re-audit and rebuild this integration to admit another
release; do not bypass the dependency.
Before installation, compare the actual packaged unit to the reviewed 5.0.0 contract;
re-audit any version change, including service sandbox access to sysfs and the runtime directory.

## Attended configuration

After PWM qualification, record exact running kernel, SHA-256 of loaded
`/sys/module/acer_wmi/notes/.note.gnu.build-id`, the canonical Acer platform device
path and hwmon name. Missing build-ID evidence fails closed; never substitute the
on-disk module's identity. Channels are exactly `pwm1_enable` and `pwm2_enable`.
Record the CPU device path/package label and NVIDIA UUID, and measured admissible
reading bounds; only then set `qualified=true`. Never store a numbered hwmon path.
The helper reads current CPU sysfs and selected NVIDIA temperature directly on each
start, rejects invalid/missing values and bounds acquisition time. It cannot detect a
hardware backend returning frozen-but-plausible values; live sensor-loss qualification
and CoolerControl's runtime failsafe remain required.

`guard` returns 1 for a clean unsupported boot or sleep/fault latch, so systemd skips
without a restart storm. `prepare-start` records ownership before its first write,
restores/readbacks both Auto modes, then checks sensors. `restore-auto` is idempotent:
without ownership it writes nothing, including after a condition skip; with ownership
it rediscovers the qualified device using the saved contract and attempts both fans.
Failure preserves ownership and latches a visible error; ordinary cleanup never clears
that latch. Runtime state is root-only and scoped to the boot ID.

Explicit recovery: stop CoolerControl, prevent external starts, then run
`sudo /usr/lib/pt31553-fan-control/session recover`. Recovery refuses an active service,
pending systemd job or sleep marker, serializes against other helper invocations,
verifies both fans Auto and only then clears the fault. It never starts curves.
A subsequent explicit start rechecks identity and sensors. Administrative writers
outside this service must remain stopped; the helper lock does not control them.

An eight-second deadline bounds ordinary userspace work, with repeating one-second
timeouts afterward so a remaining fan attempt still has a bound. Kernel/EC hangs may
prevent even a timeout from completing: measure real stop/watchdog recovery during
attended acceptance, and keep unattended startup disabled on failure.

For removal follow `ownership.txt`; retain the driver/helper until final verified Auto.
Do not remove runtime fault files to force a pass.
