. environment $@

sudo rsync -iahHAXxvz --progress sources/common/ $L4T_VERSION/
sudo rsync -iahHAXxvz --progress sources/$L4T_VERSION/ $L4T_VERSION/

if [[ x$2 == xauvidea ]]
then
   sudo rsync -iahHAXxvz --progress sources/${L4T_VERSION}_auvidea/ $L4T_VERSION/
fi


