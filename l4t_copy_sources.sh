. environment $@

sudo rsync -iahHAXxvz --progress sources/common/ $L4T_VERSION/
sudo rsync -iahHAXxvz --progress sources/$L4T_VERSION/ $L4T_VERSION/


