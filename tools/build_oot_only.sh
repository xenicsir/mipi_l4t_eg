#!/bin/bash
#******************************************************************************
# build_oot_only.sh - Build the device trees and selected nvidia-oot camera
# modules WITHOUT ever compiling the kernel (no Image, no vmlinux, no kernel
# .ko).
#
# This is the sequence a customer follows when they only want our camera
# module against their own stock kernel, instead of our full delivery package.
#
# ---------------------------------------------------------------------------
# THIS IS A DEVELOPMENT AID, NOT A BUILD PATH.
#
# It exists to reproduce, and answer questions about, what an integrator does
# on their side: build our modules against a kernel they did not build. Nothing
# it produces is meant to be delivered.
#
# The supported build is, and stays:  ./l4t_make.sh -v <ver> --build
#
# Limitations, all deliberate:
#   - produces NO package, installs nothing, signs nothing. The .ko and .dtbo
#     are left in the build tree for inspection.
#   - builds neither the kernel, nor the initramfs, nor the standalone -eg
#     kernel version the delivery package relies on.
#   - builds only the camera modules named in MODULES, plus optionally the
#     three framework modules -- never the full module tree a package ships.
#   - the nvidia-oot Module.symvers it leaves behind describes only what was
#     built, not the whole tree.
#   - it bypasses NVIDIA's own "nvidia-oot:" and "hwpm:" rules and reproduces
#     their flags by hand (srctree.*, CONFIG_TEGRA_OOT_MODULE), and forces
#     MAKECMDGOALS to get past the ifeq() guard on the conftest recipe. A BSP
#     that changes any of these breaks this script where l4t_build.sh keeps
#     working -- that is the price of not building everything.
#   - it rewrites /tmp/stock-kdir and /tmp/stock-oot on every run, and patches
#     the extracted headers package in place (aarch64 host tools replaced by
#     x86_64 ones).
#   - FRAMEWORK=1 needs sudo, to undo the root ownership l4t_copy_sources.sh
#     leaves on some directories.
#   - exercised on 36.4.4 generic only.
# ---------------------------------------------------------------------------
#
# Usage:
#   ./tools/build_oot_only.sh -v <version> [-V <vendor>] [-c <carrier-board>]
#
# Examples:
#   ./tools/build_oot_only.sh -v 36.4.4
#   ./tools/build_oot_only.sh -v 36.4.4 -V forecr
#   PRISTINE=0 ./tools/build_oot_only.sh -v 36.4.4     # keep Y16/RAW16 + build
#                                                      #   the patched framework
#   PREPARE=0  ./tools/build_oot_only.sh -v 36.4.4     # build only, reuse the tree
#
# Environment:
#   PRISTINE  1 (default) builds as a PRISTINE_KERNEL consumer would: the
#             RAW16/Y16 modes are dropped from eg-ec-mipi and the EngineCore
#             device tree modes are renumbered to match. Set to 0 to keep them,
#             which then REQUIRES our own patched tegra-camera.ko on the target.
#   PREPARE   1 (default) runs --prepare --copy-sources first, so the tree is
#             always in sync with sources/. Set to 0 to skip straight to the
#             build. Note it does NOT pass --from-scratch, which would delete
#             the version directory -- add it by hand for a clean-slate run.
#   FRAMEWORK follows PRISTINE (0 when PRISTINE=1, 1 when PRISTINE=0). When 1,
#             also builds our patched tegra-camera.ko, nvhost-nvcsi-t194.ko and
#             tegra_camera_platform.ko -- the three the delivery package ships.
#             FRAMEWORK=1 with PRISTINE=1 is refused: they are contradictory.
#   MODULES   camera modules to build (default "eg-ec-mipi.ko"). Name them explicitly:
#             the target "modules" would drag in NVIDIA's own drivers
#             (nv_imx219.c...), which need a nvidia/conftest.h that only the
#             full nvidia-oot build produces.
#******************************************************************************

set -e

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

PRISTINE=${PRISTINE:-1}
PREPARE=${PREPARE:-1}
MODULES=${MODULES:-eg-ec-mipi.ko}

# The patched framework modules and PRISTINE_KERNEL are two halves of one
# decision, so FRAMEWORK follows PRISTINE by default:
#   PRISTINE=1 -> the target keeps ITS tegra-camera.ko, our driver and DT drop
#                 the RAW16 modes to match. Shipping our framework would defeat
#                 the whole point.
#   PRISTINE=0 -> the driver and the DT declare RAW16/Y16, which only our
#                 patched framework can negotiate, so it must ship with them.
FRAMEWORK=${FRAMEWORK:-$([[ "$PRISTINE" == "1" ]] && echo 0 || echo 1)}

if [[ "$PRISTINE" == "1" && "$FRAMEWORK" == "1" ]]; then
   echo "ERROR: FRAMEWORK=1 needs PRISTINE=0 -- our framework modules and the" >&2
   echo "       PRISTINE_KERNEL build are mutually exclusive by construction." >&2
   exit 1
fi

# ── 0. sync the tree with sources/ (PREPARE=0 to skip) ──────────────────────
if [[ "$PREPARE" == "1" ]]; then
   ./l4t_make.sh "$@" --prepare --copy-sources
fi

# l4t_init resolves the version/vendor/carrier into the paths and the toolchain:
# L4T_SRC, LINUX_FOR_TEGRA_DIR, KERNEL_SUBDIR, TOOLCHAIN_PREFIX, JETSON_DIR.
. ./l4t_environment.sh
l4t_init "$@"

KDIR_OURS=$L4T_SRC/kernel/$KERNEL_SUBDIR
export CROSS_COMPILE=$TOOLCHAIN_PREFIX
export KERNEL_HEADERS=$KDIR_OURS

# PRISTINE_KERNEL is tested with ifdef, so it must be either set to 1 or left
# undefined -- passing PRISTINE_KERNEL=0 would still count as defined and
# select the wrong branch. Passed on the command line so it wins over whatever
# l4t_init exported for this vendor.
PR_VAR=()
[[ "$PRISTINE" == "1" ]] && PR_VAR=(PRISTINE_KERNEL=1)

echo "=== $L4T_VERSION / $VENDOR / $CARRIER_BOARD   PRISTINE_KERNEL=$PRISTINE"

cd "$L4T_SRC"

# ── 1. kbuild infrastructure ONLY (~5 s) ─────────────────────────────────────
#   modules_prepare is mandatory: "scripts" alone provides neither
#   asm-offsets.h nor modpost, and the module build then fails on
#   "missing argument to -mstack-protector-guard-offset="
make -C "$KDIR_OURS" ARCH=arm64 CROSS_COMPILE=$CROSS_COMPILE defconfig
make -C "$KDIR_OURS" ARCH=arm64 CROSS_COMPILE=$CROSS_COMPILE -j8 scripts
make -C "$KDIR_OURS" ARCH=arm64 CROSS_COMPILE=$CROSS_COMPILE -j8 modules_prepare

# ── 2. device trees (~3 s) -> kernel-devicetree/generic-dts/dtbs/ ────────────
#   PRISTINE_KERNEL must be passed HERE TOO: it renumbers the EngineCore modes
#   in the overlays. Building the DTs without it and the module with it yields
#   overlays declaring 6 modes for a driver that registers 4.
make dtbs "${PR_VAR[@]}"

# ── 3. STOCK headers + x86_64 host tools ─────────────────────────────────────
#   KDIR must be the nvidia-l4t-kernel-headers package, NOT a kernel tree we
#   rebuilt: only the package carries the shipped kernel's .config, generated
#   headers and Module.symvers. Without them the module still compiles but
#   comes out with no module_layout CRC and would refuse to load.
rm -rf /tmp/stock-kdir /tmp/stock-oot
dpkg-deb -x "$JETSON_DIR/$LINUX_FOR_TEGRA_DIR"/kernel/nvidia-l4t-kernel-headers_*.deb     /tmp/stock-kdir
dpkg-deb -x "$JETSON_DIR/$LINUX_FOR_TEGRA_DIR"/kernel/nvidia-l4t-kernel-oot-headers_*.deb /tmp/stock-oot
KDIR=$(find /tmp/stock-kdir/usr/src -type d -iname kernel-source | head -1)
OOT=/tmp/stock-oot/usr/src/nvidia/nvidia-oot
[[ -f "$KDIR/Module.symvers" && -f "$OOT/Module.symvers" ]] \
   || { echo "ERROR: stock headers not found under /tmp/stock-{kdir,oot}"; exit 1; }

#   the -headers package ships host tools built for aarch64 (it is meant for
#   native on-device builds): swap in the x86_64 ones step 1 just produced.
#   A customer building natively on the Jetson can skip this entirely.
while IFS= read -r t; do
   rel="${t#$KDIR/}"
   if file -b "$t" | grep -q 'ARM aarch64' && [[ -f "$KDIR_OURS/$rel" ]]; then
      cp -f "$KDIR_OURS/$rel" "$t"
   fi
done < <(find "$KDIR/scripts" -type f -executable)

# ── 4. the modules, the way the customer will build them ─────────────────────
make -C "$KDIR" M="$L4T_SRC/nvidia-oot/drivers/media/i2c" \
     ARCH=arm64 CROSS_COMPILE=$CROSS_COMPILE \
     KBUILD_EXTRA_SYMBOLS="$OOT/Module.symvers" \
     KCPPFLAGS="-I$OOT/include" \
     "${PR_VAR[@]}" \
     $MODULES

# ── 4b. the patched framework modules (only when we DO patch the framework) ──
#   Without PRISTINE_KERNEL the driver and the DT declare RAW16/Y16 modes that
#   only our patched framework can negotiate, so these three must ship with it.
#   They are the complete set: of the 105 modules in a stock updates/ tree, the
#   only one outside these three that consumes a symbol whose CRC our patches
#   change is nvhost-nvcsi-t194, which is itself one of them. The sensor drivers
#   (nv_imx219...) only use tegracam_* and tegra_camera_device_*, whose CRCs are
#   untouched -- so the customer does NOT have to rebuild them.
#   Only these three are built, by naming the .ko targets instead of the
#   "modules" goal -- "make modules" would compile the 164 modules of
#   nvidia-oot plus nvgpu, hwpm and nvdisplay to keep 3.
#
#   Caveat: this bypasses the Makefile's own "nvidia-oot:" rule and reproduces
#   its flags (srctree.*, CONFIG_TEGRA_OOT_MODULE) by hand. If NVIDIA changes
#   them in a future BSP this breaks where "make modules" would still work.
if [[ "$FRAMEWORK" == "1" ]]; then
   #   l4t_copy_sources.sh copies some directories as root; the compiler cannot
   #   write its .cmd dependency files there ("fatal error: opening dependency
   #   file"). Same guard as l4t_build.sh.
   sudo chown -R "$USER:$(id -gn)" "$L4T_SRC/nvidia-oot" "$L4T_SRC/hwpm"

   #   conftest and hwpm are the prerequisites of the nvidia-oot rule, and each
   #   resists being asked for by name in its own way:
   #     - the conftest recipe is wrapped in ifeq($(MAKECMDGOALS),modules), so
   #       "make conftest" answers "Nothing to be done" and hwpm then fails on
   #       "nvidia/conftest.h: No such file or directory". Overriding
   #       MAKECMDGOALS on the command line re-enables it.
   #     - "make hwpm", like "make nvidia-oot", forwards the goal to the kbuild
   #       sub-make, which has no such target, so hwpm is built as a plain
   #       external module instead.
   #   KERNEL_HEADERS must be the STOCK package here too, as in step 3.
   make -C "$L4T_SRC" KERNEL_HEADERS="$KDIR" MAKECMDGOALS=modules conftest
   make -C "$KDIR" M="$L4T_SRC/hwpm/drivers/tegra/hwpm" -j8 \
        ARCH=arm64 CROSS_COMPILE=$CROSS_COMPILE CONFIG_TEGRA_OOT_MODULE=m \
        srctree.hwpm="$L4T_SRC/hwpm" \
        srctree.nvconftest="$L4T_SRC/out/nvidia-conftest" \
        modules

   #   The stock Module.symvers is added to KBUILD_EXTRA_SYMBOLS because
   #   nvhost-nvcsi-t194 consumes symbols from host1x-nvhost, which lives in the
   #   same M= tree and is deliberately not built: without it modpost reports a
   #   dozen "undefined!" errors. Legitimate here -- host1x-nvhost is not among
   #   the symbols our patches change, so the stock table is the right one.
   make -C "$KDIR" M="$L4T_SRC/nvidia-oot" -j8 \
        ARCH=arm64 CROSS_COMPILE=$CROSS_COMPILE CONFIG_TEGRA_OOT_MODULE=m \
        srctree.nvidia-oot="$L4T_SRC/nvidia-oot" \
        srctree.hwpm="$L4T_SRC/hwpm" \
        srctree.nvconftest="$L4T_SRC/out/nvidia-conftest" \
        KBUILD_EXTRA_SYMBOLS="$L4T_SRC/hwpm/drivers/tegra/hwpm/Module.symvers $OOT/Module.symvers" \
        drivers/media/platform/tegra/camera/tegra-camera.ko \
        drivers/video/tegra/host/nvcsi/nvhost-nvcsi-t194.ko \
        drivers/video/tegra/camera/tegra_camera_platform.ko

   for m in drivers/media/platform/tegra/camera/tegra-camera.ko \
            drivers/video/tegra/host/nvcsi/nvhost-nvcsi-t194.ko \
            drivers/video/tegra/camera/tegra_camera_platform.ko; do
      ls -l "$L4T_SRC/nvidia-oot/$m"
   done
fi

# ── 5. check: the CRCs must be the stock kernel's and the stock OOT's ────────
for m in $MODULES; do
   KO=$L4T_SRC/nvidia-oot/drivers/media/i2c/$m
   echo "--- $m"
   modinfo -F vermagic "$KO"
   modprobe --dump-modversions "$KO" | grep -E 'tegracam|module_layout' | while read -r crc sym; do
      if [[ "$sym" == "module_layout" ]]; then
         ref=$(awk -v s="$sym" '$2==s{print $1}' "$KDIR/Module.symvers")
      else
         ref=$(awk -v s="$sym" '$2==s{print $1}' "$OOT/Module.symvers")
      fi
      [[ "$crc" == "$ref" ]] && v=OK || v="MISMATCH (stock: ${ref:-absent})"
      printf '  %-34s %s  %s\n' "$sym" "$crc" "$v"
   done
done

# ── 6. check: the kernel really was not built ───────────────────────────────
printf 'Image=%s vmlinux=%s kernel .ko=%s\n' \
   "$([[ -f $KDIR_OURS/arch/arm64/boot/Image ]] && echo YES || echo no)" \
   "$([[ -f $KDIR_OURS/vmlinux ]] && echo YES || echo no)" \
   "$(find "$KDIR_OURS" -name '*.ko' | wc -l)"
