# Existing temperature-based fan control for PT315-53

Research date: 2026-09-09. Target: Predator PT315-53 / Civic_TLS, BIOS V1.17, CachyOS 7.2.2-1. No installation, module loading, or hardware writes performed.

## Decision

**No turnkey solution with demonstrated PT315-53 V1.17 fan-curve support was established.** Prefer investigating the existing exact-model `acer_wmi` patches plus CoolerControl. This reuses a maintained curve controller and a standard kernel interface. It remains conditional on proving the firmware actually implements that interface. The accompanying adaptation investigation establishes patch applicability; applicability alone is not hardware compatibility.

The present machine has no fan/PWM hwmon endpoints, so installing a curve GUI alone cannot solve it. CoolerControl explicitly depends on writable PWM for ordinary laptop control. [CoolerControl laptop support](https://docs.coolercontrol.org/devices/laptops)

## Candidate comparison

| Candidate | Temperature curves | Exact-model evidence | Implication |
|---|---|---|---|
| Original DAM Fan Controls | Advertises and implements software curves with background daemon | Broad Acer WMI claim; no PT315-53-specific success found | Existing curve code, but driver compatibility and lifecycle remain work. [README](https://github.com/PXDiv/Div-Acer-Manager-Fan-Controls/blob/main/README.md) |
| DAMX + Div-Linuwu-Sense | Current DAMX exposes manual and firmware Auto; custom curves remain an open request | Compatibility table lists **PH315-53**, not **PT315-53** | Successor is not a complete custom-curve replacement. README says passive development. [README](https://github.com/PXDiv/Div-Acer-Manager-Max/blob/429e7040792b8eee2bf911375ebef24002028b3b/README.md), [compatibility](https://github.com/PXDiv/Div-Acer-Manager-Max/blob/429e7040792b8eee2bf911375ebef24002028b3b/Compatibility.md), [Allow creation of fan curves](https://github.com/PXDiv/Div-Acer-Manager-Max/issues/77) |
| NBFC Linux | Temperature-threshold profiles | Config tree includes PH315-52/53/54, no PT315-53 | No verified exact-model EC configuration found; adjacent-model register profiles are not evidence of compatibility. [Config tree](https://github.com/nbfc-linux/nbfc-linux/tree/main/share/nbfc/configs) |
| Patched acer_wmi + CoolerControl | Editable temperature curves; reusable CPU/GPU sensors | Two prior patches admit this DMI identity but remain unqualified | Best small-adaptation candidate; requires hardware verification before normal operation. [Prior patches](https://github.com/dannyfranca/predator-pt315-53-fan-control/tree/main/packaging/kernel/patches), [CoolerControl profiles](https://docs.coolercontrol.org/cooling/profiles), [getting started](https://docs.coolercontrol.org/getting-started) |

`Auto` in DAMX is firmware's existing thermal policy, not a user-defined software curve. Merely restoring it does not establish the requested control. The current Div-Linuwu driver implements its own paired `fan_speed` attribute and does not implement hwmon PWM; it is not a drop-in CoolerControl backend. Its code contains no PT315-53 quirk. [Div-Linuwu source, d8ea437](https://github.com/PXDiv/Div-Linuwu-Sense/blob/d8ea437d847268dd9fe2a49ae28d0723dd720968/src/linuwu_sense.c)

## What exact-model reports establish

An owner reports **PT315-53, BIOS V1.14**, Fedora 42: RGB works, Turbo does not turn on fans, LED, or overclocking. This is exact-model negative evidence for that RGB/Turbo module, not proof that every WMI fan implementation fails. It is also a different BIOS from this machine. [Turbo mode not working Predator PT315-53](https://github.com/JafarAkhondali/acer-predator-turbo-and-rgb-keyboard-linux-module/issues/245)

Bounded search covered GitHub code, repository and issue searches for PT315-53/PT315, upstream and successor compatibility/source, their visible fork inventories, NBFC's config tree, and web searches for exact-model fan-control reports. GitHub's exact-model repository search returned the user's prior project; code search returned no matches. The original had seven visible forks and DAMX's fork API returned 66 entries; these were inventoried, not all cloned or exhaustively audited. No exact-model working fork was identified. These are search limits, not a claim that no unpublished solution exists.

Other nearby tools do not close the gap: ASense advertises firmware Auto/manual/maximum with runtime discovery, and its reference platform is PHN16-72; its table has no PT315-53. Predator Sense's table distinguishes RPM/profiles/PWM and likewise lacks PT315-53. [ASense](https://github.com/fladirm/asense), [Predator Sense](https://github.com/cleyton1986/predator-sense)

Two temperature controllers for Linuwu exist, but neither supplies exact-model support: Automatic Acer Fan Control implements interpolated CPU/GPU curves, yet its script still has a TODO for graceful exit; Acer Fan Profiles targets PTX17-71 and combines curves with load and platform-profile switching. Neither is a simpler established PT315-53 route. [AAFC README](https://codeberg.org/EtiamNullam/automatic-acer-fan-control), [AAFC source](https://codeberg.org/EtiamNullam/automatic-acer-fan-control/src/commit/2ccc00cc506be1a4a19d161b634a50667961e604/scripts/aafc), [Acer Fan Profiles](https://github.com/omar-elmountassir/acer-fan-profiles)

## Kernel/frontend compatibility

The actual `acer_wmi` sysfs ABI matches CoolerControl's ordinary hwmon control. Do not confuse sysfs values with raw firmware enum values:

| sysfs `pwmN_enable` | Meaning | Raw Acer firmware mode |
|---|---|---|
| `0` | Turbo / maximum | `2` |
| `1` | Custom / software-controlled | `3` |
| `2` | Firmware Auto | `1` |

`pwmN` uses 0–255 and the driver converts to firmware percent. `3` is **not** a valid Custom value to write to `pwmN_enable`. The current upstream driver only accepts 0, 1, 2; PT315-53 is absent from its quirk table. The prior two patches add DMI/feature flags only. [Upstream acer-wmi at 893e117](https://github.com/torvalds/linux/blob/893e11787f78e43b534e252249ac3fff4d1333f8/drivers/platform/x86/acer-wmi.c#L2997), [current CachyOS acer-wmi](https://github.com/CachyOS/linux/blob/11f0a985180e84707198334e5e612c24fa947f9c/drivers/platform/x86/acer-wmi.c), [prior patch directory](https://github.com/dannyfranca/predator-pt315-53-fan-control/tree/main/packaging/kernel/patches)

CoolerControl source inspected at **28f67bf6fd3a9f328656dca1a75ef0a9db09b604** (2026-09-06):

- Generic hwmon control sets manual mode `1`, matching Acer. Reset restores the mode captured at initialization, unless already in an automatic mode. **Start the daemon with both fans in firmware Auto (`2`)** so its saved default is correct. [Fan control helpers](https://gitlab.com/coolercontrol/coolercontrol/-/blob/28f67bf6fd3a9f328656dca1a75ef0a9db09b604/coolercontrold/daemon/src/repositories/hwmon/fans.rs#L607), [hwmon settings](https://gitlab.com/coolercontrol/coolercontrol/-/blob/28f67bf6fd3a9f328656dca1a75ef0a9db09b604/coolercontrold/daemon/src/repositories/hwmon/hwmon_repo.rs#L2080)
- Graceful shutdown iterates fan channels and requests reset. A failed reset write can be logged without confirming restoration; this code is not hardware evidence. [Shutdown](https://gitlab.com/coolercontrol/coolercontrol/-/blob/28f67bf6fd3a9f328656dca1a75ef0a9db09b604/coolercontrold/daemon/src/repositories/hwmon/hwmon_repo.rs#L1988)
- Sleep handling exists, but the hwmon pre-sleep Auto write is **ThinkPad-specific**. Acer therefore needs an explicit stop/restore-before-sleep and resume strategy, or verification that firmware itself safely restores control. Do not assume general sleep support proves Acer restoration. [Pre-sleep implementation](https://gitlab.com/coolercontrol/coolercontrol/-/blob/28f67bf6fd3a9f328656dca1a75ef0a9db09b604/coolercontrold/daemon/src/repositories/hwmon/hwmon_repo.rs#L2264), [main sleep loop](https://gitlab.com/coolercontrol/coolercontrol/-/blob/28f67bf6fd3a9f328656dca1a75ef0a9db09b604/coolercontrold/daemon/src/main_loop.rs#L128)
- Stale sensor handling substitutes 100°C after eight missing-status ticks. This is useful existing protection, not assurance against a dead process, failed firmware write, or missing fan. [Failsafe constants](https://gitlab.com/coolercontrol/coolercontrol/-/blob/28f67bf6fd3a9f328656dca1a75ef0a9db09b604/coolercontrold/daemon/src/repositories/failsafe.rs#L14)
- Arch installation is documented. Final implementation must pin and inspect the actual packaged version: source-main behavior above is not a claim about the version currently installed or available in CachyOS repositories. [Arch installation](https://docs.coolercontrol.org/installation/arch)

## Next decision boundary

Proceed with the **small kernel adaptation + existing frontend** as the leading candidate. First establish sensor discovery, both fan channels, reproducible PWM response, and return to firmware Auto on this BIOS. Then settle CoolerControl's startup, stop/crash, sleep/resume and sensor-loss behavior using the actual chosen release. If the expected WMI protocol fails, neither another GUI nor a nearby model name fixes it: that result opens a focused firmware/protocol investigation.
