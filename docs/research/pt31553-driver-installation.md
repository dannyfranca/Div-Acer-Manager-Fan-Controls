# PT315-53: module build and installation route

Research: 2026-09-09. Planning only. No build, driver load/unload, installation, signing, firmware change, or fan write performed.

## Decision

Deliver a **small, kernel-version-specific pacman package containing a replacement `acer_wmi` module**. Build against the installed prepared CachyOS headers using LLVM. Put the candidate in `updates/pt31553/`; preserve the distribution's module under `kernel/` and leave the installed LTS kernel untouched. Qualify telemetry first, then PWM, then the controller. No complete kernel rebuild or Secure Boot change is currently indicated.

Use explicit package refresh for kernel upgrades initially. DKMS is a later maintenance option, not a prerequisite for installation: automatic compilation cannot establish compatibility of a copied in-tree driver with a new kernel or its firmware. This deliberately trades automatic fan-curve continuity across kernel upgrades for a smaller initial installation and an explicit stock-Auto fallback. The implementation must communicate this limitation rather than promise maintenance-free updates.

## Machine evidence, read without privilege

| Check | Observed |
|---|---|
| Running kernel / matching headers | `linux-cachyos 7.2.2-1`, `linux-cachyos-headers 7.2.2-1`; release `7.2.2-1-cachyos` |
| Recovery packages | `linux-cachyos-lts 6.18.48-1` and matching headers installed; bootability not yet verified |
| Compiler | Kernel built with clang 22.1.8; installed clang 22.1.8-2, LLVM 22.1.8-2, LLD 22.1.8-1.1 |
| Build features | Thin LTO, x86 IBT, module BTF enabled; CFI and MODVERSIONS disabled |
| Prepared build tree | `/usr/lib/modules/7.2.2-1-cachyos/build`; `.config`, `Module.symvers`, `vmlinux`, objtool, `resolve_btfids`, and `scripts/sign-file` present |
| Build dependencies | `base-devel`, make, binutils, libelf, zstd, pahole 1.31 installed |
| Driver | `acer_wmi` loaded; stock file `/usr/lib/modules/7.2.2-1-cachyos/kernel/drivers/platform/x86/acer-wmi.ko.zst` |
| Module admission | `/sys/module/module/parameters/sig_enforce` = `N`; `/sys/kernel/security/lockdown` = `[none] integrity confidentiality`; `CONFIG_MODULE_SIG_FORCE` unset |
| Signing configuration | `CONFIG_MODULE_SIG=y`, `CONFIG_MODULE_SIG_ALL=y`, SHA-512; stock module signed by build-time kernel key |
| Module search | `/usr/lib/depmod.d/search.conf`: `search updates extramodules built-in` |
| Initramfs | mkinitcpio 41.1-2; `MODULES=()`; hooks include systemd/autodetect/kms/modconf/keyboard/sd-encrypt; current preset has only `default`, no fallback image |
| Privileged checks | `sudo -n true` requires password; `/boot` loader entries/image cannot be inspected by current user |

Sources: local `/proc/config.gz`, `/sys/module/module/parameters/sig_enforce`, `/sys/kernel/security/lockdown`, package database, `modinfo acer_wmi`, header files, mkinitcpio and depmod configuration. These are time-specific observations, not persistent guarantees. The earlier machine record supplies exact identity `Acer / Predator PT315-53 / Civic_TLS / V1.17` and UEFI Secure Boot enabled.

## Source and minimum repository artifacts to implement

For the currently observed kernel, pin [CachyOS source commit `11f0a985180e84707198334e5e612c24fa947f9c`](https://github.com/CachyOS/linux/blob/11f0a985180e84707198334e5e612c24fa947f9c/drivers/platform/x86/acer-wmi.c), release `cachyos-7.2.2-1`. The previous research established acer-wmi.c SHA-256 `8e3cd3cb8ac24cd387e5d24c69bd47e1b5868ac091d1f83958a3e36273c40f83` and clean application of both prior patches. Recheck actual source and package identity during implementation. All this C file's includes are kernel/system headers; no adjacent private driver source is required. Current header configuration already enables `CONFIG_ACER_WMI=m` and `CONFIG_ACPI_PLATFORM_PROFILE=y`.

Create:

- `packaging/acer-wmi/PKGBUILD`: pinned source/patch digests; two mutually exclusive package variants `acer-wmi-pt31553-telemetry` and `acer-wmi-pt31553-pwm`; exact dependency `linux-cachyos=7.2.2-1`; matching headers as build dependency; neither replaces/conflicts with the kernel package. Avoid user-space CFLAGS/LTO injection; kernel kbuild owns compilation. Preserve BTF and sign only after any stripping, or simply use `!strip`.
- `packaging/acer-wmi/Kbuild`: `obj-m := acer-wmi.o`.
- `packaging/acer-wmi/source-lock.toml` and the existing exact-model telemetry/PWM patches, with provenance. Do not reuse the earlier whole-kernel builder or controller admission mechanism.
- `packaging/acer-wmi/acer-wmi-pt31553.install`: targeted `depmod` after install/upgrade/removal; never load, unload, enable a controller, or change fan mode from package hooks.
- `scripts/pt31553-preflight`: exact DMI/BIOS, kernel/header/source, current admission, known control ownership, candidate identity, and recovery checks.
- `scripts/pt31553-driver-check`: stock/candidate path and hashes, module metadata, loaded srcversion where available, alias resolution, relevant log capture. Persist stage and qualification results keyed to kernel, source digest, DMI, BIOS; kernel/BIOS changes invalidate hardware qualification.
- Installation/upgrade/removal instructions plus test records. Controller recovery/service artifacts belong to the companion controller research.

Both variants install the same module path and conflict with each other; upgrading from telemetry to PWM is an explicit replacement transaction. Record the selected stage in package version/manifest so an operator cannot mistake telemetry qualification for PWM qualification. [Pacman package fields and lifecycle](https://man.archlinux.org/man/PKGBUILD.5.en)

## Package coherence comes before the source lock

The controller research found stale local package metadata (CoolerControl 4.3.1 download returning 404), while a freshly downloaded mirror database offers CoolerControl 5.0.0 and kernel 7.1.8, older than the locally installed 7.2.2. Treat that as a mirror/package-coherence issue, not a reason to downgrade. First refresh through the normal trusted package workflow, review the complete proposed transaction, and establish a coherent full-system state. Never use `-Syyuu`, force dependency breaks, or partially upgrade individual libraries to satisfy the controller.

If the accepted transaction changes the kernel/headers, reboot and rebaseline DMI, actual `uname -r`, installed matching headers, toolchain and signature enforcement **before** selecting source and building. All 7.2.2 literals in this report are the observed candidate example, not permission to build it for a different final kernel. Replace the source revision, module path, exact package dependency and logs together. Leave the recovery LTS driver unmodified; repeat its boot check if its package changes. The controller research also found GPU temperature unavailable in the current NVIDIA state; establish valid GPU telemetry before accepting temperature-based control, following that research's recovery sequence.

## Build procedure, for execution session

1. Re-read model/board/BIOS, `uname -r`, package versions and current control owners. Stop on mismatch; do not force a generic `predator_v4=1` override. Ensure no DAM, prior fand, NBFC, or competing PWM service is running.
2. Download pinned source unprivileged, verify hashes, apply **only telemetry patch**, inspect the final diff. Prepare source/Kbuild outside `/usr/lib/modules`. Use installed headers unchanged; no `modules_prepare` or rebuilding the kernel configuration.
3. Build with the exact prepared tree; example after the proposed packaging artifacts exist:

   ```sh
   task_krel=7.2.2-1-cachyos
   make -C "/usr/lib/modules/$task_krel/build" M="$PWD" LLVM=1 modules
   modinfo ./acer-wmi.ko
   ```

   Require exact vermagic, expected module name/dependencies/aliases, correct stage, no unresolved symbols, and a clean build including BTF. Do not suppress modpost failures, force vermagic, or disable kernel features to make a failing build load. Packaged `vmlinux`, pahole, objtool, and resolve_btfids cover the observed build requirements. If any are missing after updates, repair matching headers/dependencies before proceeding. Build the pacman artifact unprivileged, inspect its file list and metadata, save logs and SHA-256.
4. Package the module by copying the reviewed `.ko` into the staged `usr/lib/modules/$task_krel/updates/pt31553/` directory. Avoid invoking unrestricted `make modules_install`: current configuration requests signing during that target, while the distribution's private build key is unavailable. Copying into a package preserves the intended unsigned candidate without modifying stock files.

External-module kbuild consumes the matching configured build tree and `Module.symvers`; `M=` selects an external source directory. [Linux external modules](https://docs.kernel.org/kbuild/modules.html). `LLVM=1` selects LLVM tools consistently with this kernel. [Linux LLVM build documentation](https://docs.kernel.org/kbuild/llvm.html). CachyOS deliberately ships prepared module-build files and BTF tools in its headers package. [CachyOS packaging source](https://github.com/CachyOS/linux-cachyos/blob/master/linux-cachyos/PKGBUILD)

## Secure Boot admission

The current **running kernel does not enforce module signatures**. UEFI Secure Boot being enabled does not contradict that observation. A correctly built unsigned external module can load under the observed policy, with unsigned/external-module taint expected. Do not disable Secure Boot, change boot keys, or enroll a new certificate for this installation under current conditions.

Immediately before first load, repeat sig_enforce/lockdown/config checks. If policy has changed or the kernel reports a key rejection, stop loading. Inspect the actual kernel trust/keyrings and boot chain with privilege; use an existing suitably trusted module-signing certificate only if its private key is available through the user's established mechanism. `scripts/sign-file sha512 KEY CERT MODULE` is the signing operation, followed by compression if desired; never strip afterward. A random self-signed key, DKMS-generated MOK, or sbctl firmware key is not proof of Linux module trust. Direct systemd-boot does not imply a shim/MOK enrollment path. If no usable trusted path exists, that changed environment requires a signing decision before installation continues. Never print or copy private keys into research logs. [Kernel signing and trust rules](https://docs.kernel.org/admin-guide/module-signing.html)

## Recovery and installation procedure

1. Obtain normal local administrative access in the execution session. Read `sudo bootctl list --no-pager`, `sudo bootctl status --no-pager`, loader entries and corresponding files. Verify both current and LTS kernel/initramfs exist, the encrypted-root boot arguments are correct, and the user can select the LTS entry. Actually boot the unmodified LTS once and verify desktop/storage/network, then return to current kernel. Package presence alone does not satisfy this gate. Keep LTS free of the candidate and controller startup conditional on qualified endpoints/kernel.
2. Inspect `sudo lsinitcpio /boot/initramfs-linux-cachyos.img` for `acer-wmi` and other control modules. Save the stock module hash and current boot/configuration evidence. No need to add acer_wmi to early boot just for fans.
3. Install only the inspected telemetry package using `sudo pacman -U /absolute/path/to/telemetry-package.pkg.tar.zst`. Run/verify targeted `depmod 7.2.2-1-cachyos`. `modinfo -n acer_wmi` and `modprobe --show-depends acer_wmi` must resolve to the candidate under updates. The stock path and hash must remain intact.
4. The installed module is not necessarily the loaded module. Stop relevant controller/profile-changing services for the supervised experiment, inspect `/sys/module/acer_wmi/holders` and dependencies, then attempt an ordinary `sudo modprobe -r acer_wmi`; never force removal. Load with `sudo modprobe acer_wmi`, verify loaded identity and logs. If busy, use a planned reboot after initramfs verification; do not unload unrelated WMI modules indiscriminately.
5. If acer_wmi is embedded in the current initramfs, run `sudo mkinitcpio -p linux-cachyos` after candidate changes and inspect the resulting image to verify which binary it contains. Otherwise the real-root module is sufficient and no fan-specific initramfs rebuild is required. Existing local mkinitcpio hooks do not explicitly watch `updates/pt31553/`, so do not assume package installation updates an embedded copy. If image generation fails, restore known boot artifacts/stock module and resolve before reboot. Do not rebuild or edit the LTS preset unnecessarily.
6. Require telemetry success and the stage-specific checks from the verification research. The first patch enables Predator-v4 platform-profile registration as well as hwmon; profile registration can fail before sensor registration. A loaded module with missing endpoints is failure, not telemetry proof. Avoid changing performance profiles/hotkeys during qualification.
7. Build/package the separate PWM candidate from the same pinned source plus both patches. Replace telemetry package deliberately; repeat metadata, index, image and loaded-identity checks. Establish firmware Auto and per-fan readbacks before controller enrollment. Fan register writes occur only in the supervised hardware qualification, not during packaging.
8. Only after qualification configure CoolerControl, lifecycle recovery, temperature curves, restart/reboot acceptance and enablement described by companion research. Kernel unload does not itself restore Auto: the source lacks fan-Auto restoration in remove/suspend callbacks. Restoration must occur while the candidate endpoints still exist.

`depmod` prioritizes directories according to its configuration; installed local search makes updates outrank the stock module. [depmod configuration](https://man.archlinux.org/man/depmod.d.5.en). `modprobe` resolves dependencies/indexes and normal removal can fail for a busy module. [modprobe manual](https://man.archlinux.org/man/modprobe.8.en). Initramfs-specific conclusions above derive from this machine's inspected `/etc/mkinitcpio*` and `/usr/share/libalpm/hooks/*`, not assumptions about all Arch installations.

## Kernel updates and uninstall

**Default update contract:** no unattended new-kernel PWM qualification. Exact package dependency makes an uncoordinated kernel update stop rather than silently remove curves. Do not leave the system frozen on a kernel indefinitely; follow this transition when updating:

1. Stop/disable the curve service for the transition; invoke the verified Auto recovery for both fans and confirm firmware ownership while PWM endpoints exist.
2. Remove the exact-version candidate package normally. Its removal script must regenerate module indexes; if candidate was embedded in initramfs, regenerate the current image. Confirm stock `modinfo -n` selection. The currently loaded candidate remains until normal unload/reload or reboot; ensure Auto first.
3. Perform a normal full distribution upgrade, including new matching headers; do not use a partial upgrade or force dependency breakage. Boot the new stock kernel. Firmware Auto provides cooling during the maintenance interval.
4. Refresh source lock from the matching CachyOS release, inspect upstream changes to the complete copied driver, reapply/review the minimal patch, build the new exact-release package, and repeat telemetry/PWM checks. Recheck signing policy and initramfs. Re-enable curves only after qualification. Retire the local patch when upstream exact-model support has equivalent behavior and passes the same checks.

**Uninstall permanently:** do steps 1–2 above, remove the companion controller configuration/recovery units after their last required Auto restoration, then normally load stock or reboot into it. Verify stock module path, absence of candidate in any affected initramfs, no fan controller service starting, and firmware fan behavior. If normal removal is impossible, boot verified untouched LTS and remove the package from there. Retain stock module/package artifacts and controller backups until recovery is demonstrated. Never delete the whole modules tree.

**Why not DKMS initially:** DKMS supports per-kernel compilation, allowlist constraints and automatic installation, but its original-module handling can relocate same-name stock modules and save collisions separately. That increases recovery bookkeeping for replacing an in-tree driver. A later package may use DKMS with a reviewed kernel allowlist, LLVM builds, no load-on-install, explicit stock restoration checks and an independent untouched recovery kernel. It must still refresh upstream source and distinguish a successful rebuild from hardware qualification. [DKMS upstream manual](https://github.com/dkms-project/dkms/blob/main/dkms.8.in)

## Completion evidence and remaining runtime branches

Installation is ready to execute once the above artifacts exist and build checks pass. It is successful only after candidate identity, both fan controls, Auto restoration and temperature-driven behavior survive the companion restart/suspend/reboot checks. This research does not claim that hardware support works.

Execution-only facts still to collect: real LTS boot; privileged boot entries and image contents; clean external-module compilation; actual firmware telemetry/control/Auto responses; controller failure recovery. Each has an explicit gate and fallback above. Source/API mismatch, key rejection, lost/misidentified telemetry, incorrect fan response, or failed Auto restoration stops advancement. Preserve the failing stage's logs and return to verified stock/Auto recovery; do not proceed by bypassing checks.
