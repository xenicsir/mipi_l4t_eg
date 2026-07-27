#!/bin/bash
#******************************************************************************
# extract_cti_sources.sh - Extract Connect Tech (CTI) kernel sources from their
# GPL source archive into sources/<L4T_VERSION>/Linux_for_Tegra_cti_src/
#
# This is the NON-PRISTINE counterpart of tools/extract_cti_headers.sh:
#   - extract_cti_headers.sh  -> vendor `cti_pristine`: precompiled kernel,
#     only header packages extracted, EG modules rebuilt against CTI's ABI.
#   - extract_cti_sources.sh  -> vendor `cti`: CTI's real kernel sources, used
#     as a normal vendor source layer (like Forecr), so the full EG patch set
#     (camera framework included) can be applied and a complete kernel built.
#
# CONFIDENTIAL: CTI's source archive is not publicly downloadable. It has no
# `url` in eg_config.yaml and is NEVER auto-downloaded — it must be placed
# manually under archives/CTI/ (same convention as Forecr's vendor kernel).
# If it is absent, this script exits 0 with a warning so the rest of the
# pipeline is not blocked (the `cti` build config is skipped upstream).
# The generated *_eg-delta.tgz cache below contains CTI source code too and is
# therefore equally confidential — it lives under archives/, which is entirely
# gitignored, and must never be committed or redistributed.
#
# TWO INDEPENDENT FILTERS ARE APPLIED (both are required — neither replaces
# the other):
#   1. SCOPE  — only the kernel subsystems we actually build are considered
#               (kernel-jammy-src, nvidia-oot); hardware, kernel-devicetree,
#               laird/nvgpu/nvdisplay/nvethernetrm/hwpm/uefi are ignored — see
#               the SCOPE array below for why.
#   2. DIFF   — within that scope, only files that are NEW or MODIFIED
#               relative to the pristine Nvidia BSP are kept. Scope alone is
#               not enough: kernel-jammy-src alone is a full Linux tree
#               (~70k files) of which CTI modified only a handful.
# EG's own sources are deliberately NOT filtered out here: CTI's versions land
# in the vendor layer and l4t_copy_sources.sh 3-way-merges them with the EG
# layers (pristine Nvidia BSP as common ancestor), exactly like Forecr.
#
# DELTA CACHE (*_eg-delta.tgz)
# Running the two filters above is expensive: it decompresses ~1.4 GB out of a
# 1.5 GB gzip stream and then byte-compares ~70k files. The *result*, however,
# is tiny (a few MB — only CTI's new/modified files). So the result is cached
# as <source-archive-basename>_eg-delta.tgz next to the source archive:
#   - cache present -> extracted straight into the vendor layer (near-instant,
#     and notably WITHOUT needing the 1.5 GB archive or the Nvidia BSP at all).
#   - cache absent   -> full scope+diff run, then the cache is produced.
# The cache embeds a manifest recording the L4T version, the source archive and
# the exact scope it was built from; a scope/version mismatch is reported and
# the cache is rebuilt rather than silently reused. Force a rebuild at any time
# with CTI_FORCE_REGEN=1 (or by deleting the *_eg-delta.tgz file).
#
# Archive layout (CTI) vs Nvidia BSP layout — note kernel-jammy-src is nested
# one level deeper on the Nvidia side:
#   sources/kernel/kernel-jammy-src   -> source/kernel/kernel-jammy-src
#   sources/kernel/nvidia-oot         -> source/nvidia-oot
#
# Usage:
#   ./tools/extract_cti_sources.sh <L4T_VERSION> [ARCHIVE_PATH] [NVIDIA_BSP_SRC]
#
# Example:
#   ./tools/extract_cti_sources.sh 36.5.0
#   CTI_FORCE_REGEN=1 ./tools/extract_cti_sources.sh 36.5.0
#
# Output:
#   sources/<L4T_VERSION>/Linux_for_Tegra_cti_src/source/...  (gitignored)
#   archives/CTI/<archive-basename>_eg-delta.tgz              (gitignored cache)
#******************************************************************************

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

if [[ $# -lt 1 ]]; then
   echo "Usage: $0 <L4T_VERSION> [ARCHIVE_PATH] [NVIDIA_BSP_SRC]"
   echo ""
   echo "Example:"
   echo "  $0 36.5.0"
   echo "  CTI_FORCE_REGEN=1 $0 36.5.0     # ignore and rebuild the delta cache"
   echo ""
   echo "Without ARCHIVE_PATH, looks for archives/CTI/*cti-l4t-src*<L4T_VERSION>*.tgz"
   exit 1
fi

L4T_VERSION="$1"
ARCHIVE_PATH_ARG="$2"
NVIDIA_BSP_SRC_ARG="$3"

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
ARCHIVE_DIR="$ROOT_DIR/archives/CTI"
VENDOR_LAYER="$ROOT_DIR/sources/$L4T_VERSION/Linux_for_Tegra_cti"
DEST="$VENDOR_LAYER/source"
MANIFEST_NAME=".eg-delta-manifest"

# Kernel subsystems to consider (filter 1: SCOPE).
# Values are "<path-inside-archive>:<path-inside-nvidia-source>".
# `hardware` and `kernel-devicetree` are deliberately NOT in scope:
#   - every file the vendor changes under hardware/ is one of its own board
#     device trees (cti-public/), none of which we build: the base DTB is
#     flashed by the vendor's own BSP and our package ships overlays only,
#     which come from sources/common/. Worse, building them fails outright —
#     their AGX Orin boards include a Xavier (T194) binding that L4T 36.x no
#     longer ships, breaking `make dtbs` for the whole tree.
#   - the vendor changes nothing at all under kernel-devicetree (measured: 0
#     new, 0 modified), so comparing it is pure cost.
SCOPE=(
   "kernel-jammy-src:kernel/kernel-jammy-src"
   "nvidia-oot:nvidia-oot"
)
SCOPE_ID="${SCOPE[*]}"

#******************************************************************************
# Locate the CTI source archive and its delta cache.
# Absent is NOT an error (confidential, may legitimately be missing on a
# machine that only builds the pristine variant).
#******************************************************************************
if [[ -n "$ARCHIVE_PATH_ARG" ]]; then
   CTI_ARCHIVE="$ARCHIVE_PATH_ARG"
else
   # Exclude our own *_eg-delta.tgz from the source-archive glob.
   CTI_ARCHIVE=$(ls "$ARCHIVE_DIR"/*cti-l4t-src*"$L4T_VERSION"*.tgz 2>/dev/null \
                 | grep -v '_eg-delta\.tgz$' | head -1)
fi

if [[ -n "$CTI_ARCHIVE" ]]; then
   CACHE="${CTI_ARCHIVE%.tgz}_eg-delta.tgz"
else
   # No source archive: a delta cache alone is enough to build.
   CACHE=$(ls "$ARCHIVE_DIR"/*cti-l4t-src*"$L4T_VERSION"*_eg-delta.tgz 2>/dev/null | head -1)
fi

# Nothing usable at all — neither the source archive nor a delta cache. Note
# CTI_ARCHIVE may be a non-empty path to a file that does not exist (the caller
# always passes the configured name), hence the -f test rather than -z alone.
if [[ ( -z "$CTI_ARCHIVE" || ! -f "$CTI_ARCHIVE" ) && ( -z "$CACHE" || ! -f "$CACHE" ) ]]; then
   echo -e "${YELLOW}Warning: no CTI source archive or delta cache found for L4T $L4T_VERSION — skipping.${NC}"
   echo "  Looked for: $ARCHIVE_DIR/*cti-l4t-src*${L4T_VERSION}*.tgz"
   echo "  These archives are confidential and never auto-downloaded; place one"
   echo "  there manually to enable the non-pristine 'cti' build."
   exit 0
fi

echo "============================================"
echo "Extracting CTI kernel sources for L4T $L4T_VERSION"
echo "============================================"

#******************************************************************************
# Fast path: reuse the delta cache when it matches this version + scope
#******************************************************************************
use_cache=0
if [[ -f "$CACHE" && "$CTI_FORCE_REGEN" != "1" ]]; then
   _mf=$(tar xzOf "$CACHE" "$MANIFEST_NAME" 2>/dev/null || true)
   cached_scope=$(sed -n 's/^scope: //p'               <<< "$_mf")
   cached_ver=$(sed -n 's/^l4t_version: //p'           <<< "$_mf")
   cached_size=$(sed -n 's/^source_archive_size: //p'  <<< "$_mf")
   cached_mtime=$(sed -n 's/^source_archive_mtime: //p' <<< "$_mf")

   # Size+mtime of the source archive guard against the one case the cache
   # filename cannot catch: the vendor re-spinning an archive IN PLACE under
   # the same name. A checksum would be correct too but means re-reading 1.5 GB
   # on every run — size+mtime is free and catches a real replacement.
   if [[ -n "$CTI_ARCHIVE" && -f "$CTI_ARCHIVE" ]]; then
      cur_size=$(stat -c %s "$CTI_ARCHIVE")
      cur_mtime=$(stat -c %Y "$CTI_ARCHIVE")
   else
      # Source archive absent: cache-only machine, nothing to compare against.
      cur_size="$cached_size"
      cur_mtime="$cached_mtime"
   fi

   if [[ "$cached_scope" == "$SCOPE_ID" && "$cached_ver" == "$L4T_VERSION" \
         && "$cached_size" == "$cur_size" && "$cached_mtime" == "$cur_mtime" ]]; then
      use_cache=1
   else
      echo -e "${YELLOW}  Delta cache present but stale — rebuilding. Mismatch:${NC}"
      [[ "$cached_ver"   != "$L4T_VERSION" ]] && echo "    l4t_version: cached '$cached_ver' != '$L4T_VERSION'"
      [[ "$cached_scope" != "$SCOPE_ID"    ]] && echo "    scope:       cached '$cached_scope'"
      [[ "$cached_size"  != "$cur_size"    ]] && echo "    archive size:  cached '$cached_size' != '$cur_size'"
      [[ "$cached_mtime" != "$cur_mtime"   ]] && echo "    archive mtime: cached '$cached_mtime' != '$cur_mtime' (archive replaced in place)"
   fi
fi

if [[ $use_cache -eq 1 ]]; then
   echo -e "  Source:      $(basename "$CACHE") ${GREEN}(delta cache)${NC}"
   echo "  Destination: ${DEST#$ROOT_DIR/}"
   echo ""
   echo -e "${BLUE}Extracting delta cache...${NC}"
   rm -rf "$DEST"
   mkdir -p "$VENDOR_LAYER"
   tar xzf "$CACHE" -C "$VENDOR_LAYER"
   rm -f "$VENDOR_LAYER/$MANIFEST_NAME"
   n=$(find "$DEST" -type f 2>/dev/null | wc -l)
   echo ""
   echo -e "${GREEN}Done.${NC} $n files restored from cache to ${DEST#$ROOT_DIR/}"
   echo "(Rebuild it from the full archive with CTI_FORCE_REGEN=1.)"
   exit 0
fi

#******************************************************************************
# Slow path: full scope + diff run, then build the cache
#******************************************************************************
if [[ -z "$CTI_ARCHIVE" || ! -f "$CTI_ARCHIVE" ]]; then
   echo -e "${RED}Error: delta cache unusable and no CTI source archive available.${NC}"
   echo "  Expected: $ARCHIVE_DIR/*cti-l4t-src*${L4T_VERSION}*.tgz"
   exit 1
fi

# Locate the pristine Nvidia BSP to diff against
if [[ -n "$NVIDIA_BSP_SRC_ARG" ]]; then
   NVIDIA_SRC="$NVIDIA_BSP_SRC_ARG"
else
   for cand in "$ROOT_DIR/$L4T_VERSION"/Linux_for_Tegra_cti_hadron_dm \
               "$ROOT_DIR/$L4T_VERSION"/Linux_for_Tegra_cti \
               "$ROOT_DIR/$L4T_VERSION"/Linux_for_Tegra; do
      if [[ -d "$cand/source" ]]; then
         NVIDIA_SRC="$cand/source"
         break
      fi
   done
fi

if [[ -z "$NVIDIA_SRC" || ! -d "$NVIDIA_SRC" ]]; then
   echo -e "${RED}Error: pristine Nvidia BSP source not found for L4T $L4T_VERSION${NC}"
   echo "  Run ./l4t_prepare.sh first, or pass the path as 3rd argument."
   exit 1
fi

# The diff is only meaningful against a PRISTINE Nvidia BSP. If the reference
# tree has already been through l4t_copy_sources.sh, our own EG changes are in
# it: files where the vendor matches Nvidia but we patched then show up as
# "modified by the vendor", silently inflating the result — and conversely, a
# tree that already received a previous extraction makes the vendor look like
# it changed almost nothing. Both failure modes are silent and produce a
# plausible number, so refuse rather than guess.
#
# A tree that never went through copy_sources has no git repo of its own (that
# script creates it). Careful: `git -C <dir>` walks up to an ancestor repo when
# <dir> is not one, which would report the *outer* project's changes — hence
# the explicit .git check first.
_bsp_root="$(dirname "$NVIDIA_SRC")"
if [[ -d "$_bsp_root/.git" ]]; then
   _dirty=$(sudo git -C "$_bsp_root" status --porcelain --untracked-files=no 2>/dev/null | wc -l)
   if [[ "$_dirty" -gt 0 ]]; then
      echo -e "${RED}Error: reference BSP is not pristine ($_dirty tracked modifications).${NC}" >&2
      echo "  ${_bsp_root#$ROOT_DIR/}" >&2
      echo "  l4t_copy_sources.sh has already run on it, so a diff against it would" >&2
      echo "  be meaningless. Use a freshly prepared tree (l4t_prepare.sh), or pass" >&2
      echo "  another BSP source directory as the 3rd argument." >&2
      exit 1
   fi
fi

echo "  Archive:     $(basename "$CTI_ARCHIVE")"
echo "  Nvidia BSP:  ${NVIDIA_SRC#$ROOT_DIR/}"
echo "  Destination: ${DEST#$ROOT_DIR/}"
echo "  Cache (out): ${CACHE#$ROOT_DIR/}"
echo "  Scope:       ${SCOPE[*]%%:*}"
echo ""
echo -e "${YELLOW}  Note: this full run is slow (decompresses ~1.4 GB and compares ~70k"
echo -e "  files). It happens only once — subsequent runs reuse the delta cache.${NC}"
echo ""

# The in-scope extraction is a few GB (kernel-jammy-src is a full Linux tree),
# so it must not land in a possibly-small /tmp (or a tmpfs). Stage it inside the
# CURRENT build tree (the parent of the Nvidia BSP source dir we diff against,
# e.g. <ver>/Linux_for_Tegra_cti_hadron_dm/) — it always exists by this point in
# --prepare (BSP, toolchain and kernel sources are all extracted beforehand),
# it is on the same filesystem, and being per-build it cannot collide with a
# concurrent build of another version/vendor/carrier. Override with CTI_TMPDIR.
STAGING_PARENT="${CTI_TMPDIR:-$(dirname "$NVIDIA_SRC")}"
mkdir -p "$STAGING_PARENT"
TMP=$(mktemp -d "$STAGING_PARENT/.cti-src-staging.XXXXXX")
trap 'rm -rf "$TMP"' EXIT

MEMBERS=()
for entry in "${SCOPE[@]}"; do
   MEMBERS+=("sources/kernel/${entry%%:*}")
done

echo -e "${BLUE}Extracting in-scope subsystems from archive...${NC}"
if command -v pigz &>/dev/null; then
   tar -I pigz -xf "$CTI_ARCHIVE" -C "$TMP" "${MEMBERS[@]}"
else
   tar xzf "$CTI_ARCHIVE" -C "$TMP" "${MEMBERS[@]}"
fi

echo -e "${BLUE}Comparing against pristine Nvidia BSP...${NC}"
rm -rf "$DEST"
mkdir -p "$DEST"

python3 - "$TMP/sources/kernel" "$NVIDIA_SRC" "$DEST" "${SCOPE[@]}" <<'PYEOF'
import os, shutil, sys, filecmp

cti_root, nvidia_root, dest_root = sys.argv[1], sys.argv[2], sys.argv[3]
scope = [s.split(':', 1) for s in sys.argv[4:]]

total_new = total_mod = total_same = 0
per_subsys = []

for cti_sub, nv_sub in scope:
    cti_dir = os.path.join(cti_root, cti_sub)
    nv_dir = os.path.join(nvidia_root, nv_sub)
    if not os.path.isdir(cti_dir):
        print(f"  SKIP {cti_sub}: not present in archive")
        continue

    new = mod = same = 0
    for dirpath, dirnames, filenames in os.walk(cti_dir):
        # Never descend into symlinked dirs (avoids duplicate trees, e.g.
        # scripts/dtc/include-prefixes/* aliasing arch/*/boot/dts).
        dirnames[:] = [d for d in dirnames
                       if not os.path.islink(os.path.join(dirpath, d))]
        for fn in filenames:
            src = os.path.join(dirpath, fn)
            rel = os.path.relpath(src, cti_dir)
            ref = os.path.join(nv_dir, rel)
            dst = os.path.join(dest_root, nv_sub, rel)

            if os.path.islink(src):
                # Keep a symlink only if new or retargeted
                if os.path.islink(ref) and os.readlink(ref) == os.readlink(src):
                    same += 1
                    continue
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                if os.path.lexists(dst):
                    os.remove(dst)
                os.symlink(os.readlink(src), dst)
                new += 1
                continue

            if not os.path.exists(ref):
                kind = 'new'
            elif filecmp.cmp(src, ref, shallow=False):
                same += 1
                continue
            else:
                kind = 'mod'

            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)
            if kind == 'new':
                new += 1
            else:
                mod += 1

    per_subsys.append((cti_sub, new, mod, same))
    total_new += new
    total_mod += mod
    total_same += same

print("")
print(f"  {'subsystem':<22} {'new':>8} {'modified':>10} {'identical':>11}")
print(f"  {'-'*22} {'-'*8} {'-'*10} {'-'*11}")
for name, new, mod, same in per_subsys:
    print(f"  {name:<22} {new:>8} {mod:>10} {same:>11}")
print(f"  {'-'*22} {'-'*8} {'-'*10} {'-'*11}")
print(f"  {'TOTAL':<22} {total_new:>8} {total_mod:>10} {total_same:>11}")
print("")
print(f"KEPT: {total_new + total_mod} files "
      f"(out of {total_new + total_mod + total_same} in scope)")
PYEOF

#******************************************************************************
# Build the delta cache (atomically: write to .tmp then rename, so an aborted
# run can never leave a truncated cache that later gets silently reused).
#******************************************************************************
echo -e "${BLUE}Building delta cache...${NC}"
cat > "$VENDOR_LAYER/$MANIFEST_NAME" <<EOF
# Generated by tools/extract_cti_sources.sh — do not edit.
# CONFIDENTIAL: contains Connect Tech source code. Never commit or redistribute.
# No generation date on purpose: it would be the last thing making two caches
# built from the same archive and scope differ byte for byte, defeating
# checksum comparison. Use the cache file's own mtime for that.
l4t_version: $L4T_VERSION
source_archive: $(basename "$CTI_ARCHIVE")
source_archive_size: $(stat -c %s "$CTI_ARCHIVE")
source_archive_mtime: $(stat -c %Y "$CTI_ARCHIVE")
scope: $SCOPE_ID
EOF

# Deterministic archive: same content -> same bytes, so two caches can be
# compared with a plain checksum.
#   --sort=name                stable entry order regardless of readdir order
#   --owner/--group/--numeric  no uid/gid of whoever ran the extraction
#   --clamp-mtime --mtime=…    directories are created by this run and would
#                              otherwise carry its wall-clock time (the actual
#                              cause of byte differences between two identical
#                              caches). Clamping to the source archive's mtime
#                              pins them, while leaving the files' own older
#                              timestamps untouched — they come from the vendor
#                              archive and `make` relies on them.
tar czf "$CACHE.tmp" -C "$VENDOR_LAYER" \
    --sort=name --owner=0 --group=0 --numeric-owner \
    --clamp-mtime --mtime="@$(stat -c %Y "$CTI_ARCHIVE")" \
    "$MANIFEST_NAME" source
mv -f "$CACHE.tmp" "$CACHE"
rm -f "$VENDOR_LAYER/$MANIFEST_NAME"

echo ""
echo -e "${GREEN}Done.${NC} CTI sources extracted to ${DEST#$ROOT_DIR/}"
echo "  Delta cache: ${CACHE#$ROOT_DIR/} ($(du -h "$CACHE" | cut -f1))"
echo "  Subsequent runs reuse it (near-instant, and the 1.5 GB archive is then"
echo "  no longer needed). Force a rebuild with CTI_FORCE_REGEN=1."
