# PT315-53 temperature-based fan control: implementation and installation plan

Status: Ready for installation-readiness review. Research is complete; implementation, compilation and live installation checks remain to execute.

## Intended result

CoolerControl continuously adjusts both laptop fans from CPU/GPU temperatures, retains its curve configuration across reboot, and relinquishes control to firmware when stopped or unavailable. Delivery uses the narrow exact-model acer_wmi adaptation already selected with Danny. Fixed manual fan speeds are only short verification points, not the delivered user experience.

The [wayfinder map](https://github.com/dannyfranca/Div-Acer-Manager-Fan-Controls/issues/1) tracks decisions. This document orders the implementation and installation work; the linked decision tickets and research assets retain the evidence.

## Facts and assumptions

- Confirmed target: Acer Predator PT315-53, Civic_TLS, BIOS V1.17; CachyOS 7.2.2-1 with matching headers.
- Stock acer_wmi is loaded but exposes no fan/PWM endpoints. The two earlier DMI patches fit the current source; firmware compatibility has not been demonstrated.
- User accepted the small driver adaptation plus CoolerControl and requested a plan covering all steps through installation.
- Initial curve preference is balanced cooling/noise unless Danny selects another preference. Actual temperature/duty points depend on observed firmware behavior and will be chosen during supervised setup.
- Installation must re-read current machine/package/kernel facts. A kernel update can invalidate the researched source and build assumptions.
- Current prerequisites: repository metadata is inconsistent with installed versions, NVIDIA reports "GPU requires reset" rather than a valid temperature, and the installed recovery LTS has not yet been boot-tested.
- UEFI Secure Boot is enabled but the running kernel has module-signature enforcement off and no lockdown. Keep Secure Boot enabled; recheck admission policy before loading.

## Execution order

| Stage | Work | Exit condition | If it fails |
|---|---|---|---|
| 1. Baseline and recovery | Resolve package coherence and GPU telemetry; record current kernel/module, temperatures, services, and usable stock recovery boot | Known starting state and practical route back to stock | Resolve missing recovery, invalid sensors or existing controller first |
| 2. Prepare implementation | Add narrow driver packaging and only missing CoolerControl lifecycle integration | Reviewable source/package/service artifacts; no hardware writes | Fix implementation before installing |
| 3. Build candidate | Compile/package against exact current headers and source; inspect output | Build and module metadata checks pass | Fix build/config compatibility; do not load |
| 4. Telemetry installation | Install reviewed first-stage candidate and deliberately activate it | Both fan tachometers are present and credible | Return to stock; investigate missing firmware discovery |
| 5. PWM verification | Introduce PWM support, verify mode reads, individual response and return to Auto | Both fans respond correctly and Auto restoration works | Stop control attempt; recover before removing candidate |
| 6. Curve integration | Install/configure CoolerControl and minimal service glue | Correct sensor/fan mapping and automatic temperature response | Return to Auto; fix mapping or integration |
| 7. Lifecycle checks | Check graceful stop, process failure, sleep/resume and reboot | Automatic operation resumes correctly and relinquishes control when required | Keep automatic startup disabled until fixed |
| 8. Routine use | Enable normal boot startup and record settings/recovery instructions | Curves operate after reboot with measured fan feedback | Use documented stop/Auto and rollback path |
| 9. Maintenance and removal | Preserve support across reviewed kernel/package updates; verify complete uninstall | Updates pass compatibility checks; removal restores stock behavior | Boot stock recovery and remove candidate override |

## Detailed driver procedure

Evidence and command-level detail: [driver build/install research](../../research/pt31553-driver-installation.md). The steps below are implementation work for the execution session; named package/helper artifacts do not exist yet.

1. **Establish a coherent baseline.** Refresh/review the normal trusted pacman transaction; do not force a downgrade to the inspected mirror's older kernel or partially upgrade libraries. The planned controller install is `sudo pacman -Syu coolercontrold` only after repository coherence is established. It can be installed inactive at this stage or later. Reboot/rebaseline if the kernel changes. Recheck NVIDIA temperature after a normal stock boot; if still invalid, investigate GPU health before accepting curves.
2. **Prove recovery.** With normal local administrative access, inspect boot entries and their kernel/initramfs files. Danny boots the unmodified LTS entry once and verifies usable display/input/storage/network, then returns to the target kernel. Record stock module identity/hash. Keep the candidate out of the LTS module tree and image.
3. **Implement the driver packages.** Add `packaging/acer-wmi/PKGBUILD`, `Kbuild`, source lock, and exact-model patches. Provide mutually exclusive telemetry and PWM package variants, each bound to the exact kernel version. Pin the matching CachyOS source and verify its digest; the researched 7.2.2 source is an example only if that remains the final kernel. Do not copy the prior project's whole-kernel/controller build system.
4. **Implement installation checks.** Add preflight and driver-check commands to report exact machine/kernel/header/source match, current module policy, package stage, stock/candidate resolution and loaded identity. Keep one manifest and test log. Package hooks regenerate module dependencies; they must never load a module, start control or change fan settings.
5. **Build without loading.** Compile telemetry first through the prepared matching headers using `make -C /usr/lib/modules/<release>/build M=<source-directory> LLVM=1 modules`. Inspect build output, BTF, vermagic, dependencies/aliases and package file list. Stage the module into `updates/pt31553/`; preserve the stock file under `kernel/`. Do not use force-load options or suppress build failures. Current headers/compiler/BTF tooling are available; recheck after updates.
6. **Admit telemetry deliberately.** Install the reviewed local telemetry package with pacman. Verify depmod selects it and the stock file remains unchanged. Inspect whether acer_wmi is embedded in the current initramfs; rebuild/inspect the affected image when it is. Existing hooks do not guarantee updates-directory changes reach an embedded copy. Stop competing writers, then use normal module replacement only if not busy; otherwise use a planned reboot. Distinguish the module installed on disk from the module actually loaded.
7. **Require credible fan telemetry.** Discover both fan channels by device identity, inspect repeated RPM/temperature values and logs, and check basic platform functions. The first quirk also enables platform-profile registration; missing hwmon can result from failure there. Do not advance merely because a module loaded.
8. **Introduce PWM separately.** Build/install the second package from the same verified source plus the PWM patch. Repeat path/image/loaded-identity checks. With the controller stopped, verify both mode/duty reads, establish Auto, then demonstrate a brief Custom-to-Auto transition and independent fan response. Use the acceptance procedure below.

**Signing branch:** current policy admits a matching unsigned external module, with expected external/unsigned module taint. No Secure Boot change or new key enrollment is planned. If enforcement changes or loading reports key rejection, pause for a trust-path decision; do not disable security or assume a generated key is trusted.

## Detailed controller procedure

Evidence and full contracts: [controller integration research](../../research/pt31553-controller-integration.md).

1. **Use the inspected release.** Candidate is `coolercontrold` 5.0.0-1, with its embedded local Web UI. A desktop window is optional. Use pacman signature verification; re-audit the unit/lifecycle behavior if the installed version differs. The inspected package does not auto-start via its own hooks, but verify active/enabled state after installation and keep it inactive during driver checks.
2. **Build only the missing integration.** Package a finite `session` helper, `/etc/pt31553-fan-control/device.toml`, a CoolerControl service drop-in, a sleep-preparation oneshot and dependencies for the four systemd sleep engines. Add fixture tests and an ownership/removal manifest. These proposed artifacts handle transitions; CoolerControl remains the only running fan controller.
3. **Define restoration precisely.** Helper commands cover guard, prepare-start, restore-auto, prepare/finish-sleep and explicit recover. Discover the exact Acer device each time, never by saved hwmon number. Before startup, establish and read back `pwmN_enable=2` on both channels and require fresh selected sensors. After daemon exit, attempt both channels even if one fails; verify Auto before permitting restart. Keep failures visible and latched. Explicit recover runs with the controller stopped, clears a fault only after successful verification, and never starts curves by itself.
4. **Handle stock/recovery boot correctly.** Guard must skip unsupported stock/LTS boots without touching fans. Because systemd runs post-stop cleanup even after a condition skips startup, use an ownership marker to distinguish this clean skip from fan endpoints disappearing after control began. The latter is a fault, not a reason to silently skip cleanup.
5. **Keep upstream supervision.** Preserve the inspected service's notify protocol, 30-second watchdog and restart behavior. Add verified Auto restoration through `ExecStartPre`/`ExecStopPost`; no second watchdog daemon. Measure actual recovery delay, including process termination and helper execution, during acceptance.
6. **Order sleep explicitly.** Required preparation creates a sleep marker, remembers prior controller activity, stops the daemon synchronously and verifies both fans Auto before the sleep engine starts. Failed preparation blocks sleep. Resume clears the sleep marker and restarts only a previously active controller through fresh-sensor checks. Cover cancelled/failed sleep and preserve any restoration fault latch.
7. **Test the integration before hardware use.** Fixtures cover both-fan attempts, readback mismatch/write failure, wrong/missing device, stale sensors, startup skip/post-stop behavior, lost active endpoints, explicit fault recovery, and cancelled sleep/resume. Check units with `systemd-analyze verify` and simulated ordering. Do not inject hardware failures by removing the driver during Custom mode.
8. **Configure the curves under observation.** Begin with boot profile application off. Start the guarded daemon and open `http://localhost:11987`; inspect Home → Hardware Support and detected devices. Identify actual CPU package and healthy NVIDIA GPU sources, fan identities and CoolerControl channel UIDs. In Cooling → Profiles, create one Graph curve per component, combine with Mix/Max, and assign the resulting profile to both verified fan channels. Creating a profile alone does not activate it; see the [official first-run/profile instructions](https://docs.coolercontrol.org/getting-started). Initially apply the greater requested cooling to both fans. Keep temperatures unfiltered upward; use slow downward changes to avoid oscillation. No fan-stop sweep. Choose duty floor and curve points from measurements, not another model. Ensure the high-demand end remains full demand through the controller's 100°C missing-sensor substitute.
9. **Save and promote settings.** Back up `/etc/coolercontrol/` and record actual points/source identities. Verify restart and temperature response, then the lifecycle matrix. Only after those pass enable service startup and boot profile application; perform final reboot acceptance and confirm operation with the UI closed.

## Detailed acceptance and rollback procedure

Full stage-by-stage pass/fail table, human-presence markers and lifecycle matrix: [installation verification research](../../research/pt31553-installation-verification.md).

**Hardware checks, in order:** establish both Auto mode readbacks; make a brief Custom-to-Auto transition; test two distinct moderate-to-high requests on each fan independently with the other in Auto; verify repeatable intended RPM response and restoration after each. A successful write alone is insufficient. Firmware percent conversion can round duty readback.

**Curve checks:** use short CPU-only, GPU-dominant and mixed workloads within observed operating limits. Both components must independently increase cooling demand, and RPM must respond. Observe stable down-ramping after cooling. Test ordinary-range breakpoints if necessary rather than heating to a critical temperature to prove the top point. Exact thermal stop thresholds come from actual component limits and measured headroom during execution.

**Lifecycle checks:** graceful stop, unexpected exit, existing watchdog, both sensor-loss paths, helper write/readback failure in fixtures, configured sleep/resume, reboot and continued operation without GUI/login. Include normal GPU sleep/wake and AC/battery use. A failed restoration test blocks unattended startup; fix that failure and repeat affected checks. Keep one timestamped session log/CSV, relevant journal excerpts, saved config and package manifest.

**Rollback while responsive:** stop load → stop the sole fan writer and prevent restart → restore and read back both fans Auto while the candidate remains loaded → remove/disable controller integration → remove candidate package → regenerate module dependencies and any affected initramfs → verify stock selection → boot/reload stock and verify ordinary cooling. Keep the helper and driver until restoration succeeds.

**If restoration or the system is unresponsive:** stop further tests/load, use attended normal shutdown when possible, and the verified stock recovery boot. Physical intervention may be required if the OS cannot shut down. Do not assume a warm reboot resets this embedded controller or invent an EC/battery reset procedure. Persistent abnormal cooling opens the specific firmware-recovery investigation before further control attempts.

## Kernel updates and permanent removal

Initial delivery is a **version-specific package, not automatic DKMS**. This keeps first installation and recovery smaller but requires explicit maintenance:

1. Stop curves and verify both fans Auto before the kernel transition.
2. Remove the old exact-version candidate normally; regenerate indexes/affected image and verify stock selection. Exact package dependencies must not be bypassed to force an upgrade.
3. Perform the coherent normal system update and boot the new stock kernel with matching headers. Firmware automatic cooling is the fallback during this interval.
4. Refresh/review the matching source and patch, rebuild the small package, repeat telemetry/control/Auto checks and affected lifecycle tests, then re-enable curves. A successful compilation alone is not admission.
5. Keep the LTS recovery kernel free of candidate overrides. If its package changes, recheck its bootability. Upstream exact-model support may eventually remove the local patch after verification.

Permanent uninstall follows the responsive rollback order above. Disable curve boot application and archive settings; remove only the introduced module package, helper/configuration/drop-ins and sleep dependencies. Remove optional CoolerControl packages only if no longer wanted. Keep unrelated kernel/boot/signing assets. Verify stock operation after reboot.

## Danny's required participation during execution

- Provide normal local administrative access when privileged installation/boot-file inspection begins.
- Save work and personally select/verify the recovery boot and planned reboots.
- Stay at the laptop for first driver admission, live fan-response/curve tests and disruptive lifecycle checks.
- Judge acceptable noise during initial tuning; balanced is the proposed default. The agent can prepare packages, helpers, fixtures, settings and logs.

## Handoff

The next decision is [Review the complete installation plan and remaining machine-dependent choices](https://github.com/dannyfranca/Div-Acer-Manager-Fan-Controls/issues/8). Review the explicit kernel-update maintenance tradeoff and proposed initial curve preference. Hardware outcomes are execution gates already covered by this plan; successful firmware behavior is not assumed. Once the plan is accepted, implement the listed package/helper artifacts and follow the ordered stages.

## Completion criteria

- Both intended fans have credible RPM feedback and react to temperature-driven demand, including CPU-only and GPU-only warming.
- Software control returns both fans to firmware Auto on the selected lifecycle events, with readback rather than merely assuming a write succeeded.
- Curves/settings survive restart and reboot; suspend/resume has been checked.
- A failed candidate or future incompatible kernel has an explicit stock-driver recovery path.
- Driver/controller update and complete uninstall procedures are documented and exercised to the extent needed before routine use.
- No out-of-scope RGB, battery, or performance-profile features are intentionally introduced as product requirements.

## Hardware-dependent branches

Source review cannot pre-answer firmware discovery, fan response, or model-specific restoration. If any of these fail, pause the selected route at that stage and open a narrowly specified firmware investigation with the observed failure. Do not substitute another model's identity or EC register profile.
