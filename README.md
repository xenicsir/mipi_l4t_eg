To build the environment from scratch :
======================================
<pre>
./l4t_prepare.sh 35.1
./l4t_copy_sources.sh 35.1 [auvidea]
./l4t_build.sh 35.1
</pre>

To generate a "light" image (3.5GB) for flashing :
=================================================
<pre>
./l4t_gen_delivery_image.sh 35.1 jetson-xavier-nx-devkit-emmc-dione
</pre>

To flash it to the board :
<pre>
tar xvf Linux_for_Tegra.tar.gz
cd Linux_for_Tegra
sudo ./bootloader/mksparse  -v --fillpattern=0 bootloader/system.img.raw bootloader/system.img
sudo NO_ROOTFS=1 NO_RECOVERY_IMG=1 ./flash.sh -r --no-systemimg jetson-xavier-nx-devkit-emmc-dione mmcblk0p1
</pre>

To generate a SD card image :
=============================
<pre>
cd Linux_for_Tegra/tools
./jetson-disk-image-creator.sh -o sd-blob.img -b jetson-xavier-nx-devkit
</pre>
