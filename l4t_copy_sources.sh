. environment $@

sudo rsync -iahHAXxvz --progress sources/common/ $L4T_VERSION/

sudo rsync -iahHAXxvz --progress sources/$L4T_VERSION/ $L4T_VERSION/

if [[ x$2 != x ]]
then
   sudo rsync -iahHAXxvz --progress sources/${L4T_VERSION}_$2/ $L4T_VERSION/
fi

