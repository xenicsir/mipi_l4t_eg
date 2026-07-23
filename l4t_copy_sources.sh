#!/bin/bash
#******************************************************************************
# l4t_copy_sources.sh - Copy Exosens camera sources into the L4T environment
#
# Sources are copied in layers (common -> version-specific -> SoM -> vendor ->
# carrier); when several layers touch the same file a 3-way merge is performed
# with the pristine Nvidia BSP as common ancestor. A conflict is treated as a
# FATAL error and aborts the run (see merge_copy()): it previously fell back to
# `git merge-file --union`, which silently duplicated both sides — fine for
# additive Makefiles, wrong and invisible for C sources.
#
# The script is FULLY GENERIC:
#   - Git repo is created automatically if it doesn't exist
#   - .gitignore is generated dynamically based on copied files
#
# NOTE: patch generation (patches/<version>.patch) has been disabled — see the
# commented-out "Step 5" block near the end of this file for the two reasons
# (vendor source confidentiality, and staleness/drift). The source of truth is
# sources/<version>/ + sources/common/.
#
# Usage:
#   ./l4t_copy_sources.sh -v <version> [-V <vendor>] [-c <carrier-board>]
#
# Examples:
#   ./l4t_copy_sources.sh -v 36.4.3
#   ./l4t_copy_sources.sh -v 36.4.3 -V forecr
#******************************************************************************

. l4t_environment.sh
l4t_init "$@"

if [[ ! -d $L4T_VERSION/${LINUX_FOR_TEGRA_DIR} ]]; then
   echo "Error : $L4T_VERSION/${LINUX_FOR_TEGRA_DIR} folder doesn't exist"
   exit 1
fi

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

L4T_DIR="$JETSON_DIR/${LINUX_FOR_TEGRA_DIR}"

# Pre-resolved merge results for this version+vendor.
#
# When two layers change the same region of a file the 3-way merge conflicts
# and aborts the run (see merge_copy). For the handful of files where the
# overlap is genuine and must be resolved by hand, a resolved copy can be
# placed here and it replaces the merge outright.
#
# These live under archives/ rather than in sources/ for two reasons: a
# resolved file necessarily embeds the vendor's own code (confidential for
# some vendors, hence never committable), and archives/ is both gitignored and
# never wiped by a build — unlike the vendor source layer, which is
# regenerated from the vendor archive on every --prepare.
#
# Layout: archives/<VENDOR>/merge-resolved/<version>/<path-relative-to-L4T_DIR>
# Each resolved file has a .provenance sidecar recording the SHA-256 of the two
# sides it was resolved from; if either side changes the resolution is stale and
# the run aborts rather than silently using it (see merge_copy).
RESOLVED_ROOT="$ARCHIVE_DIR/$(echo "$VENDOR" | tr '[:lower:]' '[:upper:]')/merge-resolved/$L4T_VERSION"

# Temporary file to collect all destination paths
DEST_PATHS_FILE=$(mktemp)

trap "rm -f $DEST_PATHS_FILE" EXIT

# Note: VENDOR_SOURCE_DIR is set by environment (e.g., Linux_for_Tegra_forecr)

#******************************************************************************
# Function: Copy source files with automatic 3-way merge for overlapping files
#
# Sources are copied in layers (common → version-specific → SoM → vendor → carrier).
# When a file already exists in the destination AND was modified by a previous
# layer (differs from the original BSP), this function performs a 3-way merge
# using the original Nvidia BSP file (from git) as the common ancestor.
#
# This ensures modifications from all layers are combined automatically.
# For example, if the generic layer adds a Makefile entry and the vendor layer
# adds different entries, the result will contain both.
#
# Args: source_dir dest_dir dest_prefix verbose
#******************************************************************************
merge_copy() {
   local src_dir="$1"
   local dest_dir="$2"
   local dest_prefix="$3"  # Prefix for tracking (relative to L4T_DIR)
   local verbose="$4"

   if [[ ! -d "$src_dir" ]]; then
      return
   fi

   local merge_count=0
   local copy_count=0

   [[ "$verbose" == "1" ]] && echo "Copying from $src_dir..."

   while IFS= read -r src_file; do
      local rel_path="${src_file#$src_dir/}"
      local dest_file="$dest_dir/$rel_path"

      # PRISTINE_KERNEL vendors (e.g. cti) ship a precompiled kernel/nvidia-oot
      # we don't control: skip our patches to NVIDIA's own camera framework
      # (drivers/media/platform/tegra/camera/*, include/media/*.h) so the
      # working tree stays byte-identical to the vendor's pristine source in
      # these files. Our own new driver files (drivers/media/i2c/*) are
      # untouched by this and are always copied.
      if [[ "$PRISTINE_KERNEL" == "1" ]]; then
         case "$rel_path" in
            */drivers/media/platform/*|*/include/media/*)
               [[ "$verbose" == "1" ]] && echo "  SKIP (PRISTINE_KERNEL): $rel_path"
               continue
               ;;
         esac
      fi

      # Vendored binary kernel/nvidia-oot headers (tools/extract_cti_headers.sh), tens
      # of thousands of files (~200MB) — never git-tracked EG source, and far
      # too many files for this per-file merge_copy/.gitignore mechanism
      # (designed for small curated patch sets). l4t_build.sh reads them
      # directly from sources/<ver>/Linux_for_Tegra_cti_pristine/ instead; they must
      # never be copied into the working tree at all.
      case "$rel_path" in
         cti-kdir/*|cti-oot-headers/*)
            continue
            ;;
      esac

      # Track destination path
      if [[ -n "$dest_prefix" ]]; then
         echo "${dest_prefix}/${rel_path}" >> "$DEST_PATHS_FILE"
      else
         echo "$rel_path" >> "$DEST_PATHS_FILE"
      fi

      sudo mkdir -p "$(dirname "$dest_file")"

      # Check if dest file was already modified by a previous copy layer
      if [[ -f "$dest_file" ]]; then
         # Compute git-relative path (from L4T_DIR repo root)
         local git_path="${dest_file#$L4T_DIR/}"
         local base_tmp=$(mktemp)

         if sudo git -C "$L4T_DIR" show HEAD:"$git_path" > "$base_tmp" 2>/dev/null && [[ -s "$base_tmp" ]]; then
            # Check if dest was modified from BSP by a previous layer
            if ! diff -q "$dest_file" "$base_tmp" &>/dev/null; then

               # Hand-resolved override for this file? Use it instead of
               # merging — but only if it was resolved from exactly these two
               # sides, otherwise it is stale and must be redone.
               local resolved="$RESOLVED_ROOT/$git_path"
               if [[ -f "$resolved" ]]; then
                  local prov="${resolved}.provenance"
                  local want_ours want_theirs
                  want_ours=$(sha256sum < "$dest_file" | cut -d' ' -f1)
                  want_theirs=$(sha256sum < "$src_file" | cut -d' ' -f1)
                  local got_ours got_theirs
                  got_ours=$(sed -n 's/^ours: //p'   "$prov" 2>/dev/null)
                  got_theirs=$(sed -n 's/^theirs: //p' "$prov" 2>/dev/null)

                  if [[ "$want_ours" == "$got_ours" && "$want_theirs" == "$got_theirs" ]]; then
                     sudo cp "$resolved" "$dest_file"
                     merge_count=$((merge_count + 1))
                     rm -f "$base_tmp"
                     [[ "$verbose" == "1" ]] && echo -e "  ${BLUE}RESOLVED${NC}: $git_path"
                     continue
                  fi

                  rm -f "$base_tmp"
                  echo "" >&2
                  echo -e "${RED}============================================${NC}" >&2
                  echo -e "${RED}ERROR: stale hand-resolved merge — aborting${NC}" >&2
                  echo -e "${RED}============================================${NC}" >&2
                  echo "  File:     $git_path" >&2
                  echo "  Resolved: ${resolved#$ROOT_DIR/}" >&2
                  echo "" >&2
                  [[ "$want_ours"   != "$got_ours"   ]] && echo "  The EG side changed since the resolution was made." >&2
                  [[ "$want_theirs" != "$got_theirs" ]] && echo "  The vendor side changed since the resolution was made." >&2
                  echo "" >&2
                  echo "  Redo the resolution against the current sides, then update" >&2
                  echo "  ${prov#$ROOT_DIR/}" >&2
                  echo "  with:" >&2
                  echo "    ours: $want_ours" >&2
                  echo "    theirs: $want_theirs" >&2
                  exit 1
               fi

               # Dest has prior modifications - 3-way merge
               local merge_tmp=$(mktemp)
               cp "$dest_file" "$merge_tmp"
               if git merge-file -q "$merge_tmp" "$base_tmp" "$src_file" 2>/dev/null; then
                  sudo cp "$merge_tmp" "$dest_file"
                  merge_count=$((merge_count + 1))
                  [[ "$verbose" == "1" ]] && echo -e "  ${GREEN}MERGED${NC}: $git_path"
               else
                  # Merge conflict → FATAL.
                  #
                  # This used to be force-resolved with `git merge-file
                  # --union`, which keeps BOTH sides of the conflicting hunk
                  # back to back with no markers. That is right for the
                  # additive files this was designed for (a Makefile where one
                  # layer adds `obj-m += a.o` and another `obj-m += b.o`), but
                  # almost always WRONG for C code: the two versions get
                  # duplicated, which usually still compiles and then misbehaves
                  # silently (e.g. two identical entries in
                  # camera_common_color_fmts[], where lookups return whichever
                  # comes first). Silently shipping that is worse than failing.
                  #
                  # The conflicted merge (with <<<<<<< markers) is written next
                  # to the destination file so the conflict can be inspected.
                  # $dest_file itself is left untouched.
                  local conflict_file="${dest_file}.merge-conflict"
                  sudo cp "$merge_tmp" "$conflict_file"
                  local nhunks
                  nhunks=$(grep -c '^<<<<<<<' "$merge_tmp" 2>/dev/null || echo "?")
                  rm -f "$merge_tmp" "$base_tmp"

                  echo "" >&2
                  echo -e "${RED}============================================${NC}" >&2
                  echo -e "${RED}ERROR: 3-way merge conflict — aborting${NC}" >&2
                  echo -e "${RED}============================================${NC}" >&2
                  echo "  File:      $git_path" >&2
                  echo "  Conflicts: $nhunks hunk(s)" >&2
                  echo "  Incoming:  ${src_file#$ROOT_DIR/}" >&2
                  echo "  Conflicted merge written to:" >&2
                  echo "    ${conflict_file#$JETSON_DIR/}" >&2
                  echo "" >&2
                  echo "  Two layers changed the same region of this file and the change" >&2
                  echo "  cannot be combined automatically. Resolve it by adapting the EG" >&2
                  echo "  source so it no longer overlaps the other layer's change:" >&2
                  echo "    sources/common/... or sources/$L4T_VERSION/..." >&2
                  echo "" >&2
                  echo "  Do NOT edit the build tree directly — it is regenerated on every" >&2
                  echo "  --copy-sources run." >&2
                  exit 1
               fi
               rm -f "$merge_tmp" "$base_tmp"
               continue
            fi
         fi

         rm -f "$base_tmp"
      fi

      # No merge needed - simple copy
      sudo cp -a "$src_file" "$dest_file"
      copy_count=$((copy_count + 1))
   done < <(find "$src_dir" \( -type f -o -type l \))

   if [[ $merge_count -gt 0 ]]; then
      echo "  Sources merged: $merge_count files, $copy_count copied"
   fi
}

#******************************************************************************
# Step 1: Analyze source files to copy (dry-run to get file list)
#******************************************************************************

update_status "Analyzing sources..."
echo "============================================"
echo "Analyzing Exosens sources for L4T ${L4T_VERSION_EXTENDED}"
echo "  Vendor: $VENDOR"
[[ -n "$SOM_BOARD" ]] && echo "  SoM: $SOM_BOARD"
echo "  Carrier board: $CARRIER_BOARD"
echo "============================================"

# Function to analyze what files will be copied (list source files)
analyze_copy() {
   local src_dir="$1"
   local dest_prefix="$2"

   if [[ ! -d "$src_dir" ]]; then
      return
   fi

   # List all files and symlinks in source directory
   find "$src_dir" \( -type f -o -type l \) | while read -r filepath; do
      # Get relative path from source dir
      local relpath="${filepath#$src_dir/}"

      # Vendored binary kernel/nvidia-oot headers (tools/extract_cti_headers.sh) — see
      # matching skip in merge_copy(). Never tracked/copied into the working
      # tree; excluded here too so the .gitignore-tracked-paths pass doesn't
      # walk tens of thousands of vendor files for nothing.
      case "$relpath" in
         cti-kdir/*|cti-oot-headers/*)
            continue
            ;;
      esac

      if [[ -n "$dest_prefix" ]]; then
         echo "${dest_prefix}/${relpath}" >> "$DEST_PATHS_FILE"
      else
         echo "$relpath" >> "$DEST_PATHS_FILE"
      fi
   done
}

# Analyze all source directories
analyze_copy "$ROOT_DIR/sources/common/Linux_for_Tegra" ""
analyze_copy "$ROOT_DIR/sources/$L4T_VERSION/Linux_for_Tegra" ""

if [[ $L4T_VERSION_MAJOR -ge 36 ]]; then
   analyze_copy "$ROOT_DIR/sources/common/source/hardware_36+" "source/hardware"
   analyze_copy "$ROOT_DIR/sources/common/source/nvidia-oot" "source/nvidia-oot"
else
   # hardware_32+/ contains DT overlays for all 32.x/35.x platforms (porg, jakku, concord,
   # p3768, t18x/quill). SoM selection does not change the hardware source directory.
   HW_COMMON_DIR="hardware_32+"
   analyze_copy "$ROOT_DIR/sources/common/source/$HW_COMMON_DIR" "source/public/hardware"
   analyze_copy "$ROOT_DIR/sources/common/source/nvidia-oot/drivers" "source/public/kernel/nvidia/drivers"
fi

# SoM-specific sources
if [[ -n "$SOM_SOURCE_DIR" ]]; then
   analyze_copy "$ROOT_DIR/sources/${L4T_VERSION}/$SOM_SOURCE_DIR" ""
fi

# Vendor-specific sources
if [[ -n "$VENDOR_SOURCE_DIR" ]]; then
   analyze_copy "$ROOT_DIR/sources/${L4T_VERSION}/$VENDOR_SOURCE_DIR" ""
fi

# Carrier-specific sources
if [[ -n "$CARRIER_SOURCE_DIR" ]]; then
   analyze_copy "$ROOT_DIR/sources/${L4T_VERSION}/$CARRIER_SOURCE_DIR" ""
fi

FILE_COUNT=$(wc -l < "$DEST_PATHS_FILE" 2>/dev/null || echo 0)
echo "  Found $FILE_COUNT files to copy"

#******************************************************************************
# Step 2: Generate dynamic .gitignore based on files to copy
#******************************************************************************

update_status "Generating .gitignore..."
echo ""
echo -e "${BLUE}Generating dynamic .gitignore...${NC}"

cd "$L4T_DIR"

# Extract unique directory paths that need to be tracked
TRACKED_PATHS=$(mktemp)

# For each file, add all parent directories
while IFS= read -r filepath; do
   [[ -z "$filepath" ]] && continue

   # Add the file itself
   echo "$filepath" >> "$TRACKED_PATHS"

   # Add all parent directories
   dir=$(dirname "$filepath")
   while [[ "$dir" != "." && -n "$dir" ]]; do
      echo "${dir}/" >> "$TRACKED_PATHS"
      dir=$(dirname "$dir")
   done
done < "$DEST_PATHS_FILE"

# Sort and deduplicate
sort -u "$TRACKED_PATHS" -o "$TRACKED_PATHS"

# Generate gitignore: ignore everything, then whitelist tracked paths
sudo bash -c "cat > .gitignore << 'GITIGNORE_EOF'
#=============================================================================
# Gitignore for Linux_for_Tegra - Auto-generated by l4t_copy_sources.sh
# Only tracks directories where Exosens files are copied
#=============================================================================

# Ignore everything by default
*

# Track .gitignore itself
!.gitignore

GITIGNORE_EOF"

# Add exceptions for tracked paths (directories first, then files)
while IFS= read -r path; do
   [[ -z "$path" ]] && continue
   sudo bash -c "echo '!$path' >> .gitignore"
done < "$TRACKED_PATHS"

rm -f "$TRACKED_PATHS"

#******************************************************************************
# Function: Copy all Exosens sources to L4T directory
# Args: verbose (1 or 0)
#******************************************************************************
copy_exosens_sources() {
   local verbose="$1"

   # Layer 1: Common Exosens files (shared across all L4T versions)
   merge_copy "$ROOT_DIR/sources/common/Linux_for_Tegra" "$L4T_DIR" "" "$verbose"

   # Layer 2: Version-specific generic files
   merge_copy "$ROOT_DIR/sources/$L4T_VERSION/Linux_for_Tegra" "$L4T_DIR" "" "$verbose"

   # Layer 3: Common source files (drivers, device trees)
   if [[ $L4T_VERSION_MAJOR -ge 36 ]]; then
      # L4T 36.x structure
      merge_copy "$ROOT_DIR/sources/common/source/hardware_36+" "$L4T_DIR/source/hardware" "source/hardware" "$verbose"
      merge_copy "$ROOT_DIR/sources/common/source/nvidia-oot" "$L4T_DIR/source/nvidia-oot" "source/nvidia-oot" "$verbose"
   else
      # L4T 32.x/35.x structure.
      # hardware_32+/ covers all platforms (porg, jakku, concord, p3768, t18x/quill).
      # HW_COMMON_DIR was set to "hardware_32+" in the analyze phase above.
      merge_copy "$ROOT_DIR/sources/common/source/$HW_COMMON_DIR" "$L4T_DIR/source/public/hardware" "source/public/hardware" "$verbose"
      merge_copy "$ROOT_DIR/sources/common/source/nvidia-oot/drivers" "$L4T_DIR/source/public/kernel/nvidia/drivers" "source/public/kernel/nvidia/drivers" "$verbose"
   fi

   # Layer 4: SoM-specific files (e.g. sources/32.7.1/Linux_for_Tegra_t210)
   if [[ -n "$SOM_SOURCE_DIR" ]]; then
      merge_copy "$ROOT_DIR/sources/${L4T_VERSION}/$SOM_SOURCE_DIR" "$L4T_DIR" "" "$verbose"
   fi

   # Layer 5: Vendor-specific files (e.g. sources/35.6.2/Linux_for_Tegra_forecr)
   if [[ -n "$VENDOR_SOURCE_DIR" ]]; then
      merge_copy "$ROOT_DIR/sources/${L4T_VERSION}/$VENDOR_SOURCE_DIR" "$L4T_DIR" "" "$verbose"
   fi

   # Layer 6: Carrier-specific files (e.g. sources/35.6.2/Linux_for_Tegra_dsboard_ornxs)
   if [[ -n "$CARRIER_SOURCE_DIR" ]]; then
      merge_copy "$ROOT_DIR/sources/${L4T_VERSION}/$CARRIER_SOURCE_DIR" "$L4T_DIR" "" "$verbose"
   fi
}

TRACKED_COUNT=$(grep -c '^!' .gitignore)
echo "  Generated .gitignore with $TRACKED_COUNT tracked paths"

#******************************************************************************
# Step 3: Initialize or update git repository (BEFORE copying sources)
#******************************************************************************

update_status "Preparing git repository..."
echo ""
echo -e "${BLUE}Preparing git repository...${NC}"

# Git config for automated commits
# NOTE: These were used to stamp patch-generation commits with a build identity.
# They are not needed while patch generation (Steps 5 & 6) is disabled, because
# git falls back to ~/.gitconfig / /root/.gitconfig for the bookkeeping commits.
# Re-evaluate if patch generation is re-enabled.
#git config user.email "build@exosens.com" 2>/dev/null || true
#git config user.name "Exosens Build System" 2>/dev/null || true
#sudo git config user.email "build@exosens.com" 2>/dev/null || true
#sudo git config user.name "Exosens Build System" 2>/dev/null || true

if [[ ! -d "$L4T_DIR/.git" ]]; then
   echo "  Creating new git repository..."

   sudo git init
   sudo git add .gitignore
   sudo git commit -m "Initial gitignore"

   # Commit original BSP files that exist in tracked paths
   # This ensures patches for MODIFIED files show diffs (not "new file")
   echo "  Committing original BSP files in tracked paths..."
   sudo git add -A
   if ! sudo git diff --cached --quiet 2>/dev/null; then
      sudo git commit -m "Initial state - Nvidia L4T ${L4T_VERSION} BSP"
   fi
else
   echo "  Git repository already exists, resetting to initial state..."

   # Find "Initial state" commit (preferred) or "Initial gitignore" commit
   INITIAL_COMMIT=$(sudo git log --oneline | grep "Initial state - Nvidia L4T" | head -1 | cut -d' ' -f1)
   if [[ -z "$INITIAL_COMMIT" ]]; then
      INITIAL_COMMIT=$(sudo git log --oneline | grep "Initial gitignore" | head -1 | cut -d' ' -f1)
   fi

   if [[ -n "$INITIAL_COMMIT" ]]; then
      sudo git reset --hard "$INITIAL_COMMIT"
   else
      # Fallback: just clean up
      sudo git checkout -- . 2>/dev/null || true
      sudo git clean -fd 2>/dev/null || true
   fi

   # Update .gitignore if changed
   sudo git add .gitignore
   if ! sudo git diff --cached --quiet .gitignore 2>/dev/null; then
      sudo git commit -m "Update gitignore" 2>/dev/null || true
   fi

   # Ensure "Initial state" commit exists with original BSP files
   if ! sudo git log --oneline | grep -q "Initial state - Nvidia L4T"; then
      sudo git add -A
      if ! sudo git diff --cached --quiet 2>/dev/null; then
         sudo git commit -m "Initial state - Nvidia L4T ${L4T_VERSION} BSP"
      fi
   fi
fi

# Give ownership of .git/ and the working-tree root back to the invoking user so
# that plain (non-sudo) git commands work.  The approach of writing safe.directory
# into .git/config does not work: git refuses to read the local config of a repo
# it considers "unsafe", creating a chicken-and-egg problem.
REAL_USER="${SUDO_USER:-$(id -un)}"
REAL_GROUP="$(id -gn "$REAL_USER")"
sudo chown -R "${REAL_USER}:${REAL_GROUP}" "$L4T_DIR/.git"
sudo chown "${REAL_USER}:${REAL_GROUP}" "$L4T_DIR"

#******************************************************************************
# Step 3b: Merge Exosens defconfig into vendor sources (BEFORE copying)
#
# For vendor carrier boards on L4T 35.x, we need to merge any Exosens-specific
# CONFIG options from the generic defconfig into all vendor *_defconfig files
# in the sources/ directory BEFORE copying to the working directory.
#******************************************************************************

if [[ "$VENDOR" == "forecr" && $L4T_VERSION_MAJOR -lt 36 ]]; then
   update_status "Merging defconfigs..."
   echo ""
   echo "============================================"
   echo "Merging Exosens defconfig into ${VENDOR} sources"
   echo "============================================"

   # Paths for L4T 35.x
   KERNEL_SUBDIR="kernel-5.10"
   NVIDIA_DEFCONFIG="$ROOT_DIR/sources/$L4T_VERSION/Linux_for_Tegra/source/public/kernel/$KERNEL_SUBDIR/arch/arm64/configs/defconfig"
   SOURCE_CONFIGS_DIR="$ROOT_DIR/sources/$L4T_VERSION/$VENDOR_SOURCE_DIR/source/public/kernel/$KERNEL_SUBDIR/arch/arm64/configs"
   VENDOR_REF="$SOURCE_CONFIGS_DIR/defconfig.vendor_reference"

   if [[ -f "$NVIDIA_DEFCONFIG" && -d "$SOURCE_CONFIGS_DIR" ]]; then
      echo "  Generic defconfig: $NVIDIA_DEFCONFIG"
      echo "  Vendor sources dir: $SOURCE_CONFIGS_DIR"

      # Check if vendor reference exists
      if [[ -f "$VENDOR_REF" ]]; then
         echo "  Vendor reference: $VENDOR_REF"
         echo ""

         # Extract Exosens-specific CONFIG options
         # (present in generic but not in vendor reference)
         EXOSENS_CONFIGS=()
         while IFS= read -r line; do
            [[ -z "$line" ]] && continue
            [[ "$line" =~ ^# ]] && continue
            if [[ "$line" =~ ^CONFIG_ ]]; then
               config_name=$(echo "$line" | cut -d'=' -f1)
               if ! grep -q "^${config_name}=" "$VENDOR_REF" 2>/dev/null; then
                  EXOSENS_CONFIGS+=("$line")
               fi
            fi
         done < "$NVIDIA_DEFCONFIG"

         if [[ ${#EXOSENS_CONFIGS[@]} -gt 0 ]]; then
            echo "  Exosens CONFIG options to merge:"
            for config in "${EXOSENS_CONFIGS[@]}"; do
               echo "    $config"
            done
            echo ""

            # Apply to all *_defconfig files in sources/
            merged_count=0
            total_configs_added=0

            for defconfig_file in "$SOURCE_CONFIGS_DIR"/*_defconfig; do
               [[ ! -f "$defconfig_file" ]] && continue
               [[ "$(basename "$defconfig_file")" == "defconfig.vendor_reference" ]] && continue

               filename=$(basename "$defconfig_file")
               configs_added=0

               for config in "${EXOSENS_CONFIGS[@]}"; do
                  config_name=$(echo "$config" | cut -d'=' -f1)
                  if ! grep -q "^${config_name}=" "$defconfig_file" 2>/dev/null; then
                     echo "$config" >> "$defconfig_file"
                     configs_added=$((configs_added + 1))
                  fi
               done

               if [[ $configs_added -gt 0 ]]; then
                  echo "  MERGED: $filename (+$configs_added configs)"
                  merged_count=$((merged_count + 1))
                  total_configs_added=$((total_configs_added + configs_added))
               fi
            done

            echo ""
            if [[ $merged_count -gt 0 ]]; then
               echo -e "${GREEN}  Defconfig merge complete: $merged_count files updated ($total_configs_added configs added)${NC}"
            else
               echo -e "${GREEN}  All vendor defconfigs are already up to date${NC}"
            fi
         else
            echo "  No new Exosens CONFIG options to merge."
         fi
      else
         echo -e "${YELLOW}  WARNING: Vendor reference not found: $VENDOR_REF${NC}"
         echo "  Run extract_forecr_sources.sh first to create the vendor reference."
      fi
   fi
fi

#******************************************************************************
# Step 4: Copy Exosens sources (after git init with original state)
#******************************************************************************

update_status "Copying Exosens sources..."
echo ""
echo "============================================"
echo "Copying Exosens sources for L4T ${L4T_VERSION_EXTENDED}"
echo "============================================"

copy_exosens_sources "1"

echo ""
echo "  Copy complete"


#******************************************************************************
# Step 5: Patch generation — DISABLED (kept for reference, do not re-enable
#         without addressing both points below)
#
# Two independent reasons this is switched off:
#
#  1. CONFIDENTIALITY. The generated patch is a full diff of the working tree
#     against the pristine Nvidia BSP, so for a vendor whose sources are
#     confidential (Connect Tech: "we generally prefer that our sources are not
#     published") it would embed that vendor's kernel sources verbatim — in a
#     file that then gets committed to this repository. See Scenario E in
#     docs/MIPI_DRIVER_DEVELOPMENT_GUIDE.md.
#
#  2. STALENESS/DRIFT. The patches/ directory was a recurring source of
#     problems: the files are generated from whatever sources/ happened to
#     contain at the time, are trivially out of date afterwards, and were
#     easily mistaken for a source of truth. The source of truth is, and has
#     always been, sources/<version>/ + sources/common/ — a fresh
#     l4t_copy_sources.sh run reproduces the tree exactly.
#
# Consequence: l4t_patch_sources.sh (and l4t_make.sh --patch-sources) no longer
# have any input to work with — use --copy-sources instead.
#
# PATCH_NAME="${L4T_VERSION_EXTENDED}${SOM_BOARD:+_${SOM_BOARD}}"
# PATCH_FILE="$ROOT_DIR/patches/${PATCH_NAME}.patch"
# mkdir -p "$ROOT_DIR/patches"
#
# update_status "Generating patch..."
# echo ""
# echo "============================================"
# echo "Generating patch for L4T ${L4T_VERSION_EXTENDED}"
# echo "  Output: patches/${PATCH_NAME}.patch"
# echo "============================================"
#
# cd "$L4T_DIR"
#
# # Mark new (untracked) files as intent-to-add so they appear in git diff.
# # .git/ is owned by the invoking user (chown applied in Step 3) — no sudo needed.
# git add -N .
#
# # Single unified patch: full Exosens diff vs the original Nvidia BSP commit
# git diff > "$PATCH_FILE"
#
# PATCH_FILES=$(grep -c "^diff --git" "$PATCH_FILE" 2>/dev/null || echo 0)
# PATCH_LINES=$(wc -l < "$PATCH_FILE")
# echo -e "  ${GREEN}${PATCH_NAME}.patch${NC} — ${PATCH_FILES} files, ${PATCH_LINES} lines"
#
# #*****************************************************************************
# # Step 6: Show summary of Exosens modifications
# #*****************************************************************************
#
# echo ""
# echo "============================================"
# echo "Exosens modifications — ${PATCH_NAME}.patch ($PATCH_FILES files):"
# echo "============================================"
# grep "^diff --git" "$PATCH_FILE" | sed 's|diff --git a/||; s| b/.*||' | head -20
# if [[ $PATCH_FILES -gt 20 ]]; then
#    echo "... and $((PATCH_FILES - 20)) more files"
# fi

update_status "Done"
echo ""
echo "Next steps:"
echo "  1. Build the kernel and drivers:"
echo "     ./l4t_build.sh -v $L4T_VERSION${VENDOR:+ -V $VENDOR}"
echo ""
echo "  2. Generate the delivery package:"
echo "     ./l4t_gen_delivery_package.sh -v $L4T_VERSION${VENDOR:+ -V $VENDOR} [-p <version>]"
echo "============================================"
