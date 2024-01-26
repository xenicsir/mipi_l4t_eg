To build the environment from scratch :
<pre>
./L4T_r35.1_prepare.sh
./L4T_r35.1_apply_patches.sh
./L4T_r35.1_build.sh
</pre>

To generate a "light" image (3.5GB) for flashing :
<pre>
./L4T_r35.1_gen_delivery_image.sh jetson-xavier-nx-devkit-emmc-dione
</pre>

To flash it to the board :
<pre>
tar xvf Linux_for_Tegra.tar.gz
cd Linux_for_Tegra
sudo ./bootloader/mksparse  -v --fillpattern=0 bootloader/system.img.raw bootloader/system.img
sudo NO_ROOTFS=1 NO_RECOVERY_IMG=1 ./flash.sh -r --no-systemimg jetson-xavier-nx-devkit-emmc-dione mmcblk0p1
</pre>


