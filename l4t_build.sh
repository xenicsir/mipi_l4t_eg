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

	# Use vendor defconfig if not generic
	if [[ "$CARRIER_BOARD" != "generic" ]]; then
		export KERNEL_DEF_CONFIG=$KERNEL_DEFCONFIG
	fi

	# Standalone build: use -eg suffix to create a separate kernel version
	# This avoids overwriting original kernel/modules and allows dual-boot
	if [[ $STANDALONE_BUILD -eq 1 ]]; then
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

	run_build_step "Building kernel..." \
		make -C kernel
	run_build_step "Installing kernel..." \
		sudo -E make install -C kernel
	##export IGNORE_PREEMPT_RT_PRESENCE=1
	# Fix ownership on nvidia-oot source directories before building modules.
	# For out-of-tree builds, the compiler writes .o.d dependency files directly
	# into the source directories. Directories created by sudo (via patch or copy)
	# may be root-owned, causing "Permission denied" when creating .o.d files.
	if [[ -d "$L4T_SRC/nvidia-oot" ]]; then
		sudo chown -R "$USER:$(id -gn)" "$L4T_SRC/nvidia-oot"
	fi
	run_build_step "Building kernel modules..." \
		make modules
	run_build_step "Installing modules..." \
		sudo -E make modules_install
	run_build_step "Building device trees..." \
		make dtbs
	popd

	# Copy device tree to destination dir
	update_status "Copying build artifacts..."
	sudo cp -fv $L4T_SRC/kernel-devicetree/generic-dts/dtbs/*-eg-*.dtb* $JETSON_DIR/${LINUX_FOR_TEGRA_DIR}/rootfs/boot/

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
         sudo mount --bind /proc "$ROOTFS_DIR/proc" 2>/dev/null || true
         sudo mount --bind /sys "$ROOTFS_DIR/sys" 2>/dev/null || true
         sudo mount --bind /dev "$ROOTFS_DIR/dev" 2>/dev/null || true
         sudo mount --bind /dev/pts "$ROOTFS_DIR/dev/pts" 2>/dev/null || true

         # Generate initramfs in chroot
         update_status "Running update-initramfs..."
         sudo chroot "$ROOTFS_DIR" /usr/sbin/update-initramfs -c -k "$EG_KERNEL_VERSION" 2>/dev/null || {
            echo "Warning: update-initramfs failed, trying mkinitramfs..."
            update_status "Running mkinitramfs..."
            sudo chroot "$ROOTFS_DIR" /usr/sbin/mkinitramfs -o "/boot/initrd.img-$EG_KERNEL_VERSION" "$EG_KERNEL_VERSION" 2>/dev/null || true
         }

         # Unmount filesystems
         update_status "Unmounting chroot filesystems..."
         sudo umount "$ROOTFS_DIR/dev/pts" 2>/dev/null || true
         sudo umount "$ROOTFS_DIR/dev" 2>/dev/null || true
         sudo umount "$ROOTFS_DIR/sys" 2>/dev/null || true
         sudo umount "$ROOTFS_DIR/proc" 2>/dev/null || true

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
