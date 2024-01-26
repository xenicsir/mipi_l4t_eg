patch -N -d Linux_for_Tegra/ -p1 < patches/dione_l4t.patch
patch -N -d Linux_for_Tegra/source/public/kernel/ -p1 < patches/dione_l4t_source_public_kernel.patch
patch -N -d Linux_for_Tegra/source/public/hardware/ -p1 < patches/dione_l4t_source_public_hardware.patch
