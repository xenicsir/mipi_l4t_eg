#!/bin/bash
#******************************************************************************
# l4t_build_all.sh - Build all L4T versions and generate delivery packages
#
# This script extracts supported versions and boards from the environment file
# and builds all combinations.
#
# Usage:
#   ./l4t_build_all.sh [options] [PACKAGE_VERSION]
#
# Options:
#   --from-scratch    Force deletion of build directories before building
#   --patches-only    Only generate patches (no build, no package generation)
#   --help            Show this help message
#
# Examples:
#   ./l4t_build_all.sh                    # Build all with auto version from git tag
#   ./l4t_build_all.sh 2.0.0              # Build all with specified version
#   ./l4t_build_all.sh --from-scratch     # Clean build from scratch
#   ./l4t_build_all.sh --patches-only     # Only generate patches
#******************************************************************************

set -e

#******************************************************************************
# Parse command line options
#******************************************************************************
FROM_SCRATCH=false
PATCHES_ONLY=false
PACKAGE_VERSION=""

show_help() {
   echo "Usage: $0 [options] [PACKAGE_VERSION]"
   echo ""
   echo "Options:"
   echo "  --from-scratch    Force deletion of build directories before building"
   echo "  --patches-only    Only generate patches (no build, no package generation)"
   echo "  --help            Show this help message"
   echo ""
   echo "Examples:"
   echo "  $0                    # Build all with auto version from git tag"
   echo "  $0 2.0.0              # Build all with specified version"
   echo "  $0 --from-scratch     # Clean build from scratch"
   echo "  $0 --patches-only     # Only generate patches"
   exit 0
}

while [[ $# -gt 0 ]]; do
   case "$1" in
      --from-scratch)
         FROM_SCRATCH=true
         shift
         ;;
      --patches-only)
         PATCHES_ONLY=true
         shift
         ;;
      --help|-h)
         show_help
         ;;
      -*)
         echo "Unknown option: $1"
         show_help
         ;;
      *)
         PACKAGE_VERSION="$1"
         shift
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
# Extract supported versions and boards from environment file
#******************************************************************************
extract_versions_and_boards() {
   local env_file="environment"
   local current_version=""
   local in_case=false

   # Arrays to store results
   declare -gA VERSION_BOARDS

   while IFS= read -r line; do
      # Detect version line (e.g., "32.7.1)" or "36.4.3)")
      if [[ "$line" =~ ^([0-9]+\.[0-9]+(\.[0-9]+)?)\)$ ]]; then
         current_version="${BASH_REMATCH[1]}"
         in_case=true
      # Detect board line (e.g., "generic)" or "generic|forecr)")
      elif [[ $in_case == true && "$line" =~ ^[[:space:]]*(generic(\|[a-z]+)*)\)$ ]]; then
         boards="${BASH_REMATCH[1]}"
         # Convert "generic|forecr" to "generic forecr"
         boards=$(echo "$boards" | tr '|' ' ')
         VERSION_BOARDS["$current_version"]="$boards"
         in_case=false
      # Reset on next case or esac
      elif [[ "$line" =~ ^\*\)$ || "$line" =~ ^esac$ ]]; then
         in_case=false
      fi
   done < "$env_file"
}

# Extract versions and boards
declare -A VERSION_BOARDS
extract_versions_and_boards

# Sort versions numerically
SORTED_VERSIONS=$(echo "${!VERSION_BOARDS[@]}" | tr ' ' '\n' | sort -V)

echo ""
echo "============================================"
echo "Detected configurations from environment:"
echo "============================================"
for version in $SORTED_VERSIONS; do
   echo "  $version: ${VERSION_BOARDS[$version]}"
done
echo ""

#******************************************************************************
# Build function for a single version/board combination
#******************************************************************************
build_version_board() {
   local version=$1
   local board=$2

   if [[ "$board" == "generic" ]]; then
      local dir_suffix=""
      local linux_for_tegra_dir="Linux_for_Tegra"
   else
      local dir_suffix="_${board}"
      local linux_for_tegra_dir="Linux_for_Tegra_${board}"
   fi

   echo ""
   echo "============================================"
   if [[ "$PATCHES_ONLY" == true ]]; then
      echo "Generating patches for $version $board"
   else
      echo "Building $version $board"
   fi
   echo "============================================"

   # From scratch: delete directory
   if [[ "$FROM_SCRATCH" == true ]]; then
      if [[ -d "$version/$linux_for_tegra_dir" ]]; then
         echo "Deleting $version/$linux_for_tegra_dir (--from-scratch)"
         sudo rm -rf "$version/$linux_for_tegra_dir"
      fi
   fi

   # Prepare environment if not already done
   if [[ ! -d "$version/$linux_for_tegra_dir" ]]; then
      ./l4t_prepare.sh "$version" "$board"
   fi

   # Copy sources (generates patches)
   ./l4t_copy_sources.sh "$version" "$board"

   # Build and generate package (unless patches-only mode)
   if [[ "$PATCHES_ONLY" == false ]]; then
      ./l4t_build.sh "$version" "$board"
      ./l4t_gen_delivery_package.sh "$version" "$board" "$PACKAGE_VERSION"
   fi
}

#******************************************************************************
# Main build loop
#******************************************************************************
if [[ "$PATCHES_ONLY" == false ]]; then
   DELIVERY_FOLDER="delivery/mipi_jetson-l4t-${PACKAGE_VERSION}"
   mkdir -p "$DELIVERY_FOLDER"
   echo "Delivery folder: $DELIVERY_FOLDER"
fi

for version in $SORTED_VERSIONS; do
   boards="${VERSION_BOARDS[$version]}"

   for board in $boards; do
      build_version_board "$version" "$board"
   done

   # Copy packages to delivery folder (unless patches-only mode)
   if [[ "$PATCHES_ONLY" == false && -d "$version" ]]; then
      if ls "$version"/*.deb 1>/dev/null 2>&1; then
         cp "$version"/*.deb "$DELIVERY_FOLDER/"
      fi
   fi
done

echo ""
echo "============================================"
if [[ "$PATCHES_ONLY" == true ]]; then
   echo "Patch generation completed for all versions"
else
   echo "Build completed for all versions"
   echo "Packages available in: $DELIVERY_FOLDER"
fi
echo "============================================"
