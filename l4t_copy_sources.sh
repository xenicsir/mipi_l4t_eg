. environment $@

if [[ ! -d $L4T_VERSION/${LINUX_FOR_TEGRA_DIR} ]]
then
   echo "Error : $L4T_VERSION/${LINUX_FOR_TEGRA_DIR} folder doesn't exist"
   exit
fi

sudo rsync -iahHAXxvz --progress sources/common/Linux_for_Tegra/ $L4T_VERSION/$LINUX_FOR_TEGRA_DIR/
sudo rsync -iahHAXxvz --progress sources/$L4T_VERSION/Linux_for_Tegra/ $L4T_VERSION/$LINUX_FOR_TEGRA_DIR/

if [[ x$2 != x ]]
then
   if [[ -d sources/${L4T_VERSION}/$LINUX_FOR_TEGRA_DIR ]]
   then
      sudo rsync -iahHAXxvz --progress sources/${L4T_VERSION}/$LINUX_FOR_TEGRA_DIR/ $L4T_VERSION/$LINUX_FOR_TEGRA_DIR/
   fi
fi

# Make a backup of the sources which are not built
if [[ ! -d ${JETSON_DIR}/${LINUX_FOR_TEGRA_DIR}.src ]]
then
   sudo rsync -iahHAXxvz --progress $JETSON_DIR/${LINUX_FOR_TEGRA_DIR}/ $JETSON_DIR/${LINUX_FOR_TEGRA_DIR}.src
fi
