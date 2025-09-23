#!/bin/bash

. /usr/lib/git-core/git-sh-prompt
GIT_TAG=$(echo $(__git_ps1) | sed 's/[()]//g')

if [[ x${1} = x ]]
then
   # Automatic tag version
   PACKAGE_VERSION="$GIT_TAG"
else
   # Manual version
   PACKAGE_VERSION="$1"
fi
echo PACKAGE_VERSION ${PACKAGE_VERSION}

DELIVERY_FOLDER=delivery/mipi_jetson-l4t-${PACKAGE_VERSION}

mkdir -p $DELIVERY_FOLDER
for version in 32.7.1 32.7.4 32.7.5 32.7.6 35.1 35.3.1 35.4.1 35.5.0 35.6.0 35.6.1 35.6.2 36.4 36.4.3 36.4.4
do
  if [[ ! -d $version/Linux_for_Tegra ]]
  then
	 ./l4t_prepare.sh $version
	 ./l4t_copy_sources.sh $version
	 ./l4t_build.sh $version
	 ./l4t_gen_delivery_package.sh $version generic $PACKAGE_VERSION
  fi
  cp $version/*.deb $DELIVERY_FOLDER
done

