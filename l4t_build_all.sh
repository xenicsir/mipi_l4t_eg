mkdir -p delivery
for version in 32.7.1 32.7.4 35.1 35.3.1 35.4.1 35.5.0
do
   for board in nano xavier auvidea_X230D
   do
      if [[ ! -d $version/Linux_for_Tegra_$board ]]
      then
         ./l4t_prepare.sh $version $board
         ./l4t_copy_sources.sh $version $board
         ./l4t_build.sh $version $board
         ./l4t_gen_delivery_package.sh $version $board
      fi
   done
   cp $version/*.deb delivery
done

