sudo parted -s /dev/nvme0n1 "mklabel gpt"
sudo parted -s /dev/nvme0n1 "mkpart logical 0 -1"
sudo mke2fs -F -t ext4 /dev/nvme0n1p1
export GIT_SSL_NO_VERIFY=1
git clone https://github.com/jetsonhacks/rootOnNVMe
cd rootOnNVMe
./copy-rootfs-ssd.sh
./setup-service.sh
sudo echo "/dev/mmcblk0p1       /mnt/mmcblk0p1        ext4           defaults                                      0 1" >> /mnt/etc/fstab
sudo rm -rf /mnt/boot
sudo mkdir -p /mnt/mnt/mmcblk0p1
ln -s /mnt/mmcblk0p1/boot /mnt/boot
sudo reboot
