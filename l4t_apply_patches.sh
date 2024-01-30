. environment $@

patch -r - -N -d $L4T_VERSION/Linux_for_Tegra/ -p1 < patches/$L4T_VERSION/dione_l4t.patch
patch -r - -N -d $L4T_VERSION/Linux_for_Tegra/source/public/kernel/ -p1 < patches/$L4T_VERSION/dione_l4t_source_public_kernel.patch
patch -r - -N -d $L4T_VERSION/Linux_for_Tegra/source/public/hardware/ -p1 < patches/$L4T_VERSION/dione_l4t_source_public_hardware.patch

if [[ x$2 == xauvidea ]]
then
#   if [[ -f patches/$L4T_VERSION/auvidea_*.patch ]]
#   then
      patch -r - -N -d $L4T_VERSION/Linux_for_Tegra/ -p1 < patches/$L4T_VERSION/auvidea_l4t.patch
      patch -r - -N -d $L4T_VERSION/Linux_for_Tegra/source/public/hardware/ -p1 < patches/$L4T_VERSION/auvidea_l4t_source_public_hardware.patch
#   fi
fi


