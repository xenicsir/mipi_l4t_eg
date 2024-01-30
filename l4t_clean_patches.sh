. environment $@

pushd $L4T_VERSION/Linux_for_Tegra/
git ls-files -m | xargs git rm --cached
git stash
git clean -f
popd

pushd $L4T_VERSION/Linux_for_Tegra/source/public/kernel/
git ls-files -m | xargs git rm --cached
git stash
git clean -f
popd

pushd $L4T_VERSION/Linux_for_Tegra/source/public/hardware/
git ls-files -m | xargs git rm --cached
git stash
git clean -f




