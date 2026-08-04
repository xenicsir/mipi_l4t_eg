#!/bin/bash
#******************************************************************************
# l4t_build.sh - Build kernel and modules for Exosens cameras
#
# Usage:
#   ./l4t_build.sh -v <version> [-V <vendor>] [-c <carrier-board>] [-s]
#
# Options:
#   -v, --l4t-version VERSION      L4T version (required)
#   -V, --vendor VENDOR            Vendor: generic (default), forecr
#   -c, --carrier-board BOARD      Carrier board (default depends on vendor)
#   -s, --standalone               Build standalone kernel with -eg suffix
#                                  (auto-enabled per eg_config.yaml config)
#
# The --standalone option creates a separate kernel version (e.g., 5.15.148-tegra-eg)
# that won't conflict with the original kernel. This is required for Forecr boards
# and optional for Nvidia boards.
#
# Examples:
#   ./l4t_build.sh -v 36.4.3                    # Standard build (modules only)
#   ./l4t_build.sh -v 36.4.3 --standalone       # Standalone build with -eg suffix
#   ./l4t_build.sh -v 36.4.3 -V forecr          # Forecr build (standalone per config)
#   ./l4t_build.sh -v 35.6.1 -V forecr -s       # Forecr build with manual standalone
#******************************************************************************

# Source environment (parses all arguments including --standalone)
. l4t_environment.sh
l4t_init "$@"

# PRISTINE_KERNEL is exported by l4t_init above. No extra plumbing needed
# here: make imports it automatically from the environment into every
# invocation below (including under sudo -E), so the i2c/overlay Makefiles
# can gate obj-m/dtbo-y entries and ccflags-y with plain ifdef/ifndef.

# Guard variable: set to ROOTFS_DIR just before mounting, cleared after unmounting.
# The trap uses it to clean up bind-mounts if the script is interrupted mid-chroot.
_CHROOT_ROOTFS_DIR=""

# Repeatedly umount $1 until it's no longer a mountpoint. A single umount only
# pops the topmost layer — if a previous run left N stale binds stacked here
# (e.g. the SSH session died mid-chroot with no signal to trigger the EXIT
# trap below), one call isn't enough to actually free the target.
#
# ⚠️ Refuses any target that resolves to a filesystem of the HOST. Once
# "$rootfs/dev" is a bind of /dev, the path "$rootfs/dev/pts" resolves to the
# host's own /dev/pts -- same superblock, verified with stat -c %d -- so an
# umount there is an `umount /dev/pts` in disguise. It normally fails EBUSY
# (ptys in use) and the old `|| break` swallowed that silently; on an idle
# machine it would succeed and detach the host's devpts. This guard is why the
# function can be called on paths under a chroot without that risk.
_umount_all() {
    local target="$1" tries=0
    # Never a host path, whatever the caller passed.
    case "$target" in
        /|/dev|/dev/pts|/proc|/sys)
            echo "  refuse umount $target (host path)" >&2; return 1 ;;
    esac
    # The aliasing trap: only "<rootfs>/dev/pts" is affected. It sits INSIDE the
    # bind of /dev, so it resolves to the host's own /dev/pts -- same superblock.
    # "<rootfs>/proc", "<rootfs>/sys" and "<rootfs>/dev" are mountpoints in their
    # own right, so they share the host superblock too and must NOT be refused on
    # that basis; only the /dev/pts case is.
    # Superblock equality is the whole test, with no condition on the parent: if
    # the parent /dev is bound the path IS the host's devpts and must be refused,
    # and if it is not bound the path is a plain directory on the rootfs
    # filesystem, whose superblock differs, so this never fires spuriously.
    if [[ "$target" == */dev/pts ]] \
       && [[ "$(stat -c %d "$target" 2>/dev/null)" == "$(stat -c %d /dev/pts 2>/dev/null)" ]]; then
        echo "  refuse umount $target: resolves to the host's /dev/pts" >&2
        return 1
    fi
    while mountpoint -q "$target" 2>/dev/null; do
        if ! sudo umount "$target" 2>&1; then
            echo "  umount $target failed after $tries layer(s) removed" >&2
            return 1
        fi
        tries=$((tries + 1))
        [[ $tries -ge 20 ]] && { echo "  umount $target: 20-layer cap hit" >&2; return 1; }
    done
    return 0
}

# Bind-mount $1 onto $2, first clearing any stale bind already stacked there
# from an interrupted previous run — otherwise repeated interrupted builds
# keep stacking duplicate binds on the same target forever (only a reboot,
# or a manual cleanup, clears them; see l4t_build.sh pty-exhaustion incident).
_bind_mount_clean() {
    local src="$1" dst="$2"
    _umount_all "$dst"
    sudo mount --bind "$src" "$dst" 2>/dev/null || true
}

# Only /proc, /sys and /dev are ever bound (see below), so only those three are
# unmounted. The previous version also unmounted dev/pts, dev/shm, dev/mqueue and
# dev/hugepages -- none of which this script ever mounts. Since they live INSIDE
# the /dev bind, those calls were umounts of the host's own filesystems; they
# failed EBUSY and the silent `|| break` hid it, leaving the real cleanup undone.
_cleanup_chroot() {
    [[ -z "$_CHROOT_ROOTFS_DIR" ]] && return
    local rdir="$_CHROOT_ROOTFS_DIR"
    _umount_all "$rdir/dev"
    _umount_all "$rdir/sys"
    _umount_all "$rdir/proc"
}
trap _cleanup_chroot EXIT

#******************************************************************************
# Static verification of source DTSIs (eg_config.yaml)
#******************************************************************************
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ "${NO_VERIFY_DTSI:-0}" -eq 1 ]]; then
    echo "=== Skipping DTSI verification (--no-verify-dtsi) ==="
else
    echo "=== Verifying DTSI structure ==="
    if ! python3 "$SCRIPT_DIR/tools/verify_dtsi_structure.py" --quiet; then
        echo "ERROR: DTSI structure verification failed. Fix errors above before building." >&2
        exit 1
    fi
    echo "DTSI structure OK"
fi

#******************************************************************************
# Helper: run a build command and abort on failure
# Usage: run_build_step "description" command args...
#******************************************************************************
run_build_step() {
   local description="$1"
   shift
   update_status "$description"
   if ! "$@"; then
      echo ""
      echo "============================================"
      echo "ERROR: $description FAILED"
      echo "  Command: $*"
      echo "============================================"
      exit 1
   fi
}

if [[ ! -d $L4T_SRC ]]; then
   echo "Error : $L4T_SRC folder doesn't exist"
   exit 1
fi

echo "============================================"
echo "Building L4T ${L4T_VERSION_EXTENDED}"
echo "  Vendor: $VENDOR"
echo "  Carrier board: $CARRIER_BOARD"
echo "  Defconfig: $KERNEL_DEFCONFIG"
echo "  Standalone: $STANDALONE_BUILD"
echo "============================================"

sudo mkdir -p $JETSON_DIR/${LINUX_FOR_TEGRA_DIR}/rootfs/boot/eg

KERNEL_SOURCES=kernel/kernel-*

if [[ $L4T_VERSION_MAJOR -lt 36 ]]; then

	TEGRA_KERNEL_OUT=$L4T_SRC/build
	KERNEL_MODULES_OUT=$L4T_SRC/modules

	# Standalone build: use -eg suffix to create a separate kernel version
	if [[ $STANDALONE_BUILD -eq 1 ]]; then
		LOCALVERSION=-tegra-eg
		echo "Building standalone kernel with LOCALVERSION=$LOCALVERSION"
	else
		LOCALVERSION=-tegra
	fi

	pushd $L4T_SRC
	run_build_step "Configuring kernel..." \
		make -C $KERNEL_SOURCES ARCH=arm64 O=$TEGRA_KERNEL_OUT LOCALVERSION=$LOCALVERSION CROSS_COMPILE=${TOOLCHAIN_PREFIX} $KERNEL_DEFCONFIG
	run_build_step "Building kernel Image..." \
		make -C $KERNEL_SOURCES ARCH=arm64 O=$TEGRA_KERNEL_OUT LOCALVERSION=$LOCALVERSION CROSS_COMPILE=${TOOLCHAIN_PREFIX} -j8 Image
	run_build_step "Building device trees..." \
		make -C $KERNEL_SOURCES ARCH=arm64 O=$TEGRA_KERNEL_OUT LOCALVERSION=$LOCALVERSION CROSS_COMPILE=${TOOLCHAIN_PREFIX} -j8 dtbs
	run_build_step "Building kernel modules..." \
		make -C $KERNEL_SOURCES ARCH=arm64 O=$TEGRA_KERNEL_OUT LOCALVERSION=$LOCALVERSION CROSS_COMPILE=${TOOLCHAIN_PREFIX} -j8 modules
	run_build_step "Installing modules..." \
		make -C $KERNEL_SOURCES ARCH=arm64 O=$TEGRA_KERNEL_OUT modules_install INSTALL_MOD_PATH=$KERNEL_MODULES_OUT
	popd

	# Copy device tree to destination dir
	update_status "Copying build artifacts..."
	cp -fv $L4T_SRC/build/arch/arm64/boot/dts/* $JETSON_DIR/${LINUX_FOR_TEGRA_DIR}/kernel/dtb/
	cp -fv $L4T_SRC/build/arch/arm64/boot/dts/nvidia/* $JETSON_DIR/${LINUX_FOR_TEGRA_DIR}/kernel/dtb/
	sudo cp -fv $L4T_SRC/build/arch/arm64/boot/dts/*-eg-*.dtb* $JETSON_DIR/${LINUX_FOR_TEGRA_DIR}/rootfs/boot/
	sudo cp -fv $L4T_SRC/build/arch/arm64/boot/dts/nvidia/*-eg-*.dtb* $JETSON_DIR/${LINUX_FOR_TEGRA_DIR}/rootfs/boot
	# Copy modules to destination dir
	sudo rsync --exclude nvgpu.ko -aHAX $L4T_SRC/modules/lib/modules/ $JETSON_DIR/${LINUX_FOR_TEGRA_DIR}/rootfs/lib/modules

else

	TEGRA_KERNEL_OUT=$L4T_SRC/$KERNEL_SOURCES

	pushd $L4T_SRC
	export CROSS_COMPILE=${TOOLCHAIN_PREFIX}
	export KERNEL_HEADERS=$TEGRA_KERNEL_OUT
	export INSTALL_MOD_PATH=$JETSON_DIR/${LINUX_FOR_TEGRA_DIR}/rootfs

	# kernel-noble (L4T 39.x): tegra_ivc/tegra_hv symbols are built into vmlinux.
	# Makefile.config.noble activates NV_OOT_IVC_EXT_SKIP_BUILD=y + NV_OOT_TEGRA_HV_SKIP_BUILD=y
	# to replace the OOT modules with stubs and avoid the modpost "exported twice" error.
	[[ "$KERNEL_SUBDIR" == "kernel-noble" ]] && export kernel_name=noble

	# Use vendor defconfig if not generic
	if [[ "$CARRIER_BOARD" != "generic" ]]; then
		export KERNEL_DEF_CONFIG=$KERNEL_DEFCONFIG
	fi

	# Standalone build: use -eg suffix to create a separate kernel version
	# This avoids overwriting original kernel/modules and allows dual-boot
	if [[ $STANDALONE_BUILD -eq 1 ]]; then
		if [[ "$KERNEL_SUBDIR" == "kernel-noble" ]]; then
			# 39.x: source/kernel/Makefile gives priority to env LOCALVERSION (ifndef guard).
			# Read SRU from the kernel changelog to match its own logic, then append -eg.
			KERNEL_CHANGELOG="$L4T_SRC/kernel/${KERNEL_SUBDIR}/debian.nvidia-tegra/changelog"
			NV_SRU=""
			if command -v dpkg-parsechangelog &>/dev/null && [[ -f "$KERNEL_CHANGELOG" ]]; then
				NV_SRU=$(dpkg-parsechangelog -l "$KERNEL_CHANGELOG" -S version 2>/dev/null | cut -d'-' -f2 | cut -d'.' -f1)
			fi
			if [[ -n "$NV_SRU" ]]; then
				export LOCALVERSION="-${NV_SRU}-tegra-eg"
			else
				export LOCALVERSION="-tegra-eg"
			fi
			echo "Building standalone kernel with LOCALVERSION=${LOCALVERSION}"
		else
			# 36.x: source/kernel/Makefile uses LOCALVERSION_SUFFIX ?= variable
			export LOCALVERSION_SUFFIX=-eg
			echo "Building standalone kernel with LOCALVERSION_SUFFIX=-eg"

			# Patch kernel/Makefile to support LOCALVERSION_SUFFIX if not already patched
			KERNEL_MAKEFILE="$L4T_SRC/kernel/Makefile"
			if [[ -f "$KERNEL_MAKEFILE" ]] && ! grep -q "LOCALVERSION_SUFFIX" "$KERNEL_MAKEFILE"; then
				echo "Patching kernel/Makefile to support LOCALVERSION_SUFFIX..."
				sed -i 's/# LOCALVERSION : -tegra or -rt-tegra/# LOCALVERSION : -tegra or -rt-tegra, with optional suffix (e.g., -eg)\nLOCALVERSION_SUFFIX ?=/' "$KERNEL_MAKEFILE"
				sed -i 's/echo "-rt-tegra" || echo "-tegra")/echo "-rt-tegra$(LOCALVERSION_SUFFIX)" || echo "-tegra$(LOCALVERSION_SUFFIX)")/' "$KERNEL_MAKEFILE"
			fi
		fi
	fi

	# Fix ownership on source directories before building.
	# Directories created by sudo (via patch or copy) may be root-owned,
	# causing "Permission denied" when the compiler writes build artifacts.
	if [[ -d "$L4T_SRC/nvidia-oot" ]]; then
		sudo chown -R "$USER:$(id -gn)" "$L4T_SRC/nvidia-oot"
	fi
	if [[ -d "$L4T_SRC/kernel" ]]; then
		sudo chown -R "$USER:$(id -gn)" "$L4T_SRC/kernel"
	fi
	run_build_step "Building kernel..." \
		make -C kernel
	run_build_step "Installing kernel..." \
		sudo -E make install -C kernel
	##export IGNORE_PREEMPT_RT_PRESENCE=1
	run_build_step "Building kernel modules..." \
		make modules
	run_build_step "Installing modules..." \
		sudo -E make modules_install

	# PRISTINE_KERNEL vendors (e.g. cti) ship a precompiled kernel/nvidia-oot we
	# don't control (see cti_pristine_kernel_porting.md in shared memory). The
	# EG i2c modules just installed above were built against OUR OWN
	# kernel/nvidia-oot, whose ABI (Module.symvers CRCs, struct layouts) does
	# NOT match the vendor's real running kernel. Recompile just those modules
	# against the vendor's real, precompiled kernel + nvidia-oot headers
	# (extracted by tools/extract_cti_headers.sh), then overwrite the ones just
	# installed. Everything else built above (Image, dtbs, hwpm, nvgpu,
	# tegra-camera.ko...) is kept for pipeline consistency but never
	# flashed/deployed for this vendor.
	#
	# Read straight from sources/<ver>/Linux_for_Tegra_cti_pristine/ (never copied into
	# the working tree — l4t_copy_sources.sh explicitly skips cti-kdir/
	# cti-oot-headers: ~27000 vendored files, far too many for its per-file
	# merge_copy/.gitignore-tracking mechanism, and there's nothing to gain
	# from a working-tree copy). We do write into cti-kdir/scripts/ below
	# (removing stale prebuilt aarch64 host tools) — harmless, re-extracted
	# fresh by tools/extract_cti_headers.sh whenever it's rerun.
	if [[ "$PRISTINE_KERNEL" == "1" ]]; then
		CTI_SRC_DIR="$ROOT_DIR/sources/$L4T_VERSION/Linux_for_Tegra_cti_pristine"
		CTI_KDIR_LINUX_HEADERS=$(find "$CTI_SRC_DIR/cti-kdir/usr/src" -maxdepth 1 -mindepth 1 -type d -iname "linux-headers-*" 2>/dev/null | head -1)
		CTI_KDIR=""
		[[ -n "$CTI_KDIR_LINUX_HEADERS" ]] && CTI_KDIR=$(find "$CTI_KDIR_LINUX_HEADERS" -maxdepth 4 -type d -iname "kernel-source" 2>/dev/null | head -1)
		CTI_OOT_ROOT="$CTI_SRC_DIR/cti-oot-headers/usr/src/nvidia/nvidia-oot"
		CTI_I2C_DIR="$L4T_SRC/nvidia-oot/drivers/media/i2c"

		if [[ -z "$CTI_KDIR" || ! -f "$CTI_OOT_ROOT/Module.symvers" ]]; then
			echo "ERROR: CTI headers not found under sources/$L4T_VERSION/Linux_for_Tegra_cti_pristine/."
			echo "  Run: ./tools/extract_cti_headers.sh $L4T_VERSION"
			exit 1
		fi

		# CTI's kernel-source tree ships prebuilt host build tools (fixdep,
		# modpost, conf, dtc, kallsyms...) compiled for aarch64 — this
		# "linux-headers" package is meant for native on-device builds, not
		# x86_64-hosted cross-compilation. It's a real Debian-style
		# headers-only package (zero .c files anywhere in it), so these can't
		# be rebuilt from source here ("No rule to make target
		# scripts/basic/fixdep.c"). Substitute the equivalent host tools our
		# own earlier full generic build (make -C kernel, same job, above)
		# already produced for x86_64 from the same L4T 36.5.0 kbuild
		# infrastructure — fixdep/modpost etc. don't depend on CTI's
		# board-specific kernel patches, only on the generic kbuild version,
		# so they're safe to swap in at the same scripts/ paths.
		#
		# TEGRA_KERNEL_OUT holds an unexpanded glob (kernel/kernel-*, never
		# resolved at assignment time — every other use of it in this script
		# relies on it being referenced unquoted so the shell expands it on
		# use). Resolve it to a real path once here so it can be quoted safely.
		TEGRA_KERNEL_OUT_REAL=$(cd $TEGRA_KERNEL_OUT && pwd)
		while IFS= read -r hosttool; do
			rel="${hosttool#$CTI_KDIR/}"
			ours="$TEGRA_KERNEL_OUT_REAL/$rel"
			if file "$hosttool" 2>/dev/null | grep -q "ARM aarch64" && [[ -f "$ours" ]]; then
				cp -f "$ours" "$hosttool"
			fi
		done < <(find "$CTI_KDIR/scripts" -type f -executable 2>/dev/null)

		# Target the 2 EG .ko files by name (not the generic "modules" target):
		# source/nvidia-oot/drivers/media/i2c/Makefile also declares NVIDIA's
		# own stock drivers (max9295.c, nv_imx219.c...), which need
		# nvidia/conftest.h — generated by the full nvidia-oot build we're
		# deliberately bypassing here. Naming our .ko targets explicitly
		# builds only them (and their -objs/-y deps), never touching the
		# stock drivers.
		run_build_step "Rebuilding EG modules against real CTI kernel ABI..." \
			make -C "$CTI_KDIR" M="$CTI_I2C_DIR" \
				ARCH=arm64 CROSS_COMPILE="${TOOLCHAIN_PREFIX}" \
				KBUILD_EXTRA_SYMBOLS="$CTI_OOT_ROOT/Module.symvers" \
				KCPPFLAGS="-I$CTI_OOT_ROOT/include" \
				PRISTINE_KERNEL=1 \
				dione_ir.ko eg-ec-mipi.ko

		for mod in dione_ir eg-ec-mipi; do
			installed=$(find "$JETSON_DIR/${LINUX_FOR_TEGRA_DIR}/rootfs/lib/modules" -name "${mod}.ko" 2>/dev/null | head -1)
			built="$CTI_I2C_DIR/${mod}.ko"
			if [[ -n "$installed" && -f "$built" ]]; then
				sudo cp -fv "$built" "$installed"
			else
				echo "ERROR: could not overwrite $mod.ko against real CTI ABI (installed=$installed built=$built)"
				exit 1
			fi
		done
	fi

	run_build_step "Building device trees..." \
		make dtbs
	popd

	# Copy device tree to destination dir
	update_status "Copying build artifacts..."
	# 36.x: kernel-devicetree/generic-dts/dtbs/  — 39.x: build/nvidia-public/devicetree/generic-dtbs/
	if [[ "$KERNEL_SUBDIR" == "kernel-noble" ]]; then
		DTBS_SRC="$L4T_SRC/build/nvidia-public/devicetree/generic-dtbs"
	else
		DTBS_SRC="$L4T_SRC/kernel-devicetree/generic-dts/dtbs"
	fi
	sudo cp -fv "$DTBS_SRC"/*-eg-*.dtb* $JETSON_DIR/${LINUX_FOR_TEGRA_DIR}/rootfs/boot/

fi

# Copy kernel Image to destination dir
update_status "Copying kernel Image..."
cp -rfv $TEGRA_KERNEL_OUT/arch/arm64/boot/Image $JETSON_DIR/${LINUX_FOR_TEGRA_DIR}/kernel/
sudo cp -rfv $TEGRA_KERNEL_OUT/arch/arm64/boot/Image $JETSON_DIR/${LINUX_FOR_TEGRA_DIR}/rootfs/boot/eg

pushd $JETSON_DIR/${LINUX_FOR_TEGRA_DIR}/
if [[ -f ./tools/l4t_update_initrd.sh ]]; then
   update_status "Updating initrd..."
   sudo ./tools/l4t_update_initrd.sh
fi
popd

#******************************************************************************
# Generate initramfs for standalone builds
# For standalone builds (-eg suffix), we generate a specific initramfs that
# matches the standalone kernel version and copy it to /boot/eg/initrd-eg
#******************************************************************************
if [[ $STANDALONE_BUILD -eq 1 ]]; then
   echo ""
   echo "============================================"
   echo "Generating initramfs for standalone kernel"
   echo "============================================"

   ROOTFS_DIR=$JETSON_DIR/${LINUX_FOR_TEGRA_DIR}/rootfs

   # Find the standalone kernel version (with -eg suffix)
   EG_KERNEL_VERSION=$(ls $ROOTFS_DIR/lib/modules/ 2>/dev/null | grep -- '-eg$' | head -1)

   if [[ -n "$EG_KERNEL_VERSION" ]]; then
      echo "Kernel version: $EG_KERNEL_VERSION"

      # Generate initramfs using chroot with QEMU (arm64 emulation)
      # This requires binfmt_misc and qemu-user-static to be installed
      if [[ -f "$ROOTFS_DIR/usr/sbin/update-initramfs" ]]; then
         update_status "Generating initramfs in chroot..."

         # Ensure QEMU is available in rootfs
         if [[ -f /usr/bin/qemu-aarch64-static ]]; then
            sudo cp /usr/bin/qemu-aarch64-static "$ROOTFS_DIR/usr/bin/" 2>/dev/null || true
         fi

         # Mount required filesystems for chroot
         update_status "Mounting chroot filesystems..."
         _CHROOT_ROOTFS_DIR="$ROOTFS_DIR"
         _bind_mount_clean /proc     "$ROOTFS_DIR/proc"
         _bind_mount_clean /sys      "$ROOTFS_DIR/sys"
         _bind_mount_clean /dev      "$ROOTFS_DIR/dev"
         # NO separate bind of /dev/pts. Binding /dev already makes pts visible
         # in the chroot, and "$ROOTFS_DIR/dev/pts" resolves to the host's own
         # /dev/pts through that bind -- so this line used to stack a bind onto
         # the HOST's devpts, once per build, while its own pre-umount silently
         # failed EBUSY. That is what accumulated 7 stacked mounts on /dev/pts
         # and up to 9 per rootfs (found 2026-08-04).

         # Generate initramfs in chroot
         update_status "Running update-initramfs..."
         sudo chroot "$ROOTFS_DIR" /usr/sbin/update-initramfs -c -k "$EG_KERNEL_VERSION" 2>/dev/null || {
            echo "Warning: update-initramfs failed, trying mkinitramfs..."
            update_status "Running mkinitramfs..."
            sudo chroot "$ROOTFS_DIR" /usr/sbin/mkinitramfs -o "/boot/initrd.img-$EG_KERNEL_VERSION" "$EG_KERNEL_VERSION" 2>/dev/null || true
         }

         # Unmount only what we mounted. Anything under "$ROOTFS_DIR/dev/" is the
         # host's, reached through the /dev bind -- see _cleanup_chroot.
         update_status "Unmounting chroot filesystems..."
         _umount_all "$ROOTFS_DIR/dev"
         _umount_all "$ROOTFS_DIR/sys"
         _umount_all "$ROOTFS_DIR/proc"
         _CHROOT_ROOTFS_DIR=""

         # Move initramfs to boot/eg/initrd-eg
         if [[ -f "$ROOTFS_DIR/boot/initrd.img-$EG_KERNEL_VERSION" ]]; then
            sudo mv "$ROOTFS_DIR/boot/initrd.img-$EG_KERNEL_VERSION" "$ROOTFS_DIR/boot/eg/initrd-eg"
            echo "Created: rootfs/boot/eg/initrd-eg"
         else
            echo "Warning: initramfs was not generated"
         fi
      else
         echo "Warning: update-initramfs not found in rootfs, skipping initramfs generation"
      fi
   else
      echo "Warning: No standalone kernel modules found (expected *-eg)"
   fi
fi

update_status "Done"
echo ""
echo "============================================"
echo "Build completed for L4T ${L4T_VERSION_EXTENDED}"
echo "============================================"
echo ""
echo "Next steps:"
echo "  Generate the delivery package:"
echo "  ./l4t_gen_delivery_package.sh -v $L4T_VERSION${VENDOR:+ -V $VENDOR} [-p <version>]"
echo "============================================"

#-----------------------------#
# Flash to the Jetson board   #
#-----------------------------#
# For examples :
#sudo ./flash.sh jetson-xavier-nx-devkit-emmc-dione mmcblk0p1
#sudo ./flash.sh jetson-agx-orin-devkit mmcblk0p1
