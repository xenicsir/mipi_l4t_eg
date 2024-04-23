. environment $@

if [[ ! -d $L4T_VERSION/${LINUX_FOR_TEGRA_DIR} ]]
then
   echo "Error : $L4T_VERSION/${LINUX_FOR_TEGRA_DIR} folder doesn't exist"
   exit
fi

pushd $L4T_VERSION/$LINUX_FOR_TEGRA_DIR/
git ls-files -m | xargs git rm --cached
git stash
git clean -f
popd

pushd $L4T_VERSION/$LINUX_FOR_TEGRA_DIR/source/public/kernel/
git ls-files -m | xargs git rm --cached
git stash
git clean -f
popd

pushd $L4T_VERSION/$LINUX_FOR_TEGRA_DIR/source/public/hardware/
git ls-files -m | xargs git rm --cached
git stash
git clean -f




