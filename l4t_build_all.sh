#!/bin/bash
#******************************************************************************
# l4t_build_all.sh - Build all L4T versions and generate delivery packages
#
# This script extracts supported versions and vendors from the environment file
# and builds all combinations.
#
# Usage:
#   ./l4t_build_all.sh [options]
#
# Options:
#   -p, --package-version VERSION  Package version for all builds
#   --from-scratch                 Force deletion of build directories before building
#   --patches-only                 Only generate patches (no build, no package generation)
#   -h, --help                     Show this help message
#
# Examples:
#   ./l4t_build_all.sh                           # Build all with auto version from git tag
#   ./l4t_build_all.sh -p 2.0.0                  # Build all with specified version
#   ./l4t_build_all.sh --from-scratch            # Clean build from scratch
#   ./l4t_build_all.sh --patches-only            # Only generate patches
#******************************************************************************

set -e

#******************************************************************************
# Parse command line options
#******************************************************************************
FROM_SCRATCH=false
PATCHES_ONLY=false
PACKAGE_VERSION=""

show_help() {
   echo "Usage: $0 [options]"
   echo ""
   echo "Options:"
   echo "  -p, --package-version VERSION  Package version for all builds"
   echo "  --from-scratch                 Force deletion of build directories before building"
   echo "  --patches-only                 Only generate patches (no build, no package generation)"
   echo "  -h, --help                     Show this help message"
   echo ""
   echo "Examples:"
   echo "  $0                           # Build all with auto version from git tag"
   echo "  $0 -p 2.0.0                  # Build all with specified version"
   echo "  $0 --from-scratch            # Clean build from scratch"
   echo "  $0 --patches-only            # Only generate patches"
   exit 0
}

while [[ $# -gt 0 ]]; do
   case "$1" in
      -p|--package-version)
         PACKAGE_VERSION="$2"
         shift 2
         ;;
      --from-scratch)
         FROM_SCRATCH=true
         shift
         ;;
      --patches-only)
         PATCHES_ONLY=true
         shift
         ;;
      -h|--help)
         show_help
         ;;
      *)
         echo "Unknown option: $1"
         show_help
         ;;
   esac
done

#******************************************************************************
# Get package version from git tag if not specified
#******************************************************************************
. /usr/lib/git-core/git-sh-prompt
GIT_TAG=$(echo $(__git_ps1) | sed 's/[()]//g')

if [[ -z "$PACKAGE_VERSION" ]]; then
   PACKAGE_VERSION="$GIT_TAG"
fi
echo "PACKAGE_VERSION: ${PACKAGE_VERSION}"

#******************************************************************************
# Define supported versions and vendors
#******************************************************************************
# Format: "VERSION:VENDORS" where VENDORS is space-separated
declare -a CONFIGURATIONS=(
   "32.7.1:generic"
   "32.7.4:generic"
   "32.7.5:generic"
   "32.7.6:generic"
   "35.1:generic"
   "35.3.1:generic forecr"
   "35.4.1:generic forecr"
   "35.5.0:generic forecr"
   "35.6.0:generic forecr"
   "35.6.1:generic forecr"
   "35.6.2:generic forecr"
   "36.4:generic forecr"
   "36.4.3:generic forecr"
   "36.4.4:generic forecr"
)

echo ""
echo "============================================"
echo "Supported configurations:"
echo "============================================"
for config in "${CONFIGURATIONS[@]}"; do
   version="${config%%:*}"
   vendors="${config#*:}"
   echo "  $version: $vendors"
done
echo ""

#******************************************************************************
# Build function for a single version/vendor combination
#******************************************************************************
build_version_vendor() {
   local version=$1
   local vendor=$2

   # Determine directory name based on vendor
   if [[ "$vendor" == "generic" ]]; then
      local linux_for_tegra_dir="Linux_for_Tegra"
   else
      # Default carrier-board for vendor (forecr -> dsboard_ornx)
      local carrier_board="dsboard_ornx"
      local linux_for_tegra_dir="Linux_for_Tegra_${vendor}_${carrier_board}"
   fi

   echo ""
   echo "============================================"
   if [[ "$PATCHES_ONLY" == true ]]; then
      echo "Generating patches for $version ($vendor)"
   else
      echo "Building $version ($vendor)"
   fi
   echo "============================================"

   # Build argument list
   local args="-v $version"
   if [[ "$vendor" != "generic" ]]; then
      args="$args -V $vendor"
   fi

   # From scratch: delete directory
   if [[ "$FROM_SCRATCH" == true ]]; then
      if [[ -d "$version/$linux_for_tegra_dir" ]]; then
         echo "Deleting $version/$linux_for_tegra_dir (--from-scratch)"
         sudo rm -rf "$version/$linux_for_tegra_dir"
      fi
   fi

   # Prepare environment if not already done
   if [[ ! -d "$version/$linux_for_tegra_dir" ]]; then
      ./l4t_prepare.sh $args
   fi

   # Copy sources (generates patches)
   ./l4t_copy_sources.sh $args

   # Build and generate package (unless patches-only mode)
   if [[ "$PATCHES_ONLY" == false ]]; then
      ./l4t_build.sh $args

      # Add package version argument if specified
      local pkg_args="$args"
      if [[ -n "$PACKAGE_VERSION" ]]; then
         pkg_args="$pkg_args -p $PACKAGE_VERSION"
      fi
      ./l4t_gen_delivery_package.sh $pkg_args
   fi
}

#******************************************************************************
# Main build loop
#******************************************************************************
for config in "${CONFIGURATIONS[@]}"; do
   version="${config%%:*}"
   vendors="${config#*:}"

   for vendor in $vendors; do
      build_version_vendor "$version" "$vendor"
   done
done

echo ""
echo "============================================"
if [[ "$PATCHES_ONLY" == true ]]; then
   echo "Patch generation completed for all versions"
else
   echo "Build completed for all versions"
fi
echo "============================================"
