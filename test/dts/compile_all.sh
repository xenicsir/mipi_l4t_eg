#!/bin/bash
# Compiles all DTS test fixtures to DTB/DTBO files.
# Output goes to /boot/dtbs/ (mounted tmpfs inside container).
set -e

DTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT_DIR="${TEST_DTBS_DIR:-/boot/dtbs}"
mkdir -p "$OUT_DIR"

compile() {
    local src="$DTS_DIR/$1.dts"
    local out="$OUT_DIR/$1.dtb"
    dtc -I dts -O dtb -o "$out" "$src" 2>/dev/null
    echo "  compiled $1.dts → $1.dtb"
}

compile_overlay() {
    local src="$DTS_DIR/$1.dts"
    local out="$OUT_DIR/$1.dtbo"
    dtc -I dts -O dtb -@ -o "$out" "$src" 2>/dev/null
    echo "  compiled $1.dts → $1.dtbo"
}

echo "Compiling base DTBs..."
compile base_no_imx
compile base_imx219_active
compile base_imx219_disabled
compile base_imx477_active
compile base_imx219_imx477_active

echo "Compiling overlay DTBOs..."
compile_overlay overlay_eg_cams
compile_overlay overlay_eg_cams_forecr
compile_overlay overlay_disable_imx219
compile_overlay overlay_disable_imx477
compile_overlay overlay_eg_lane
compile_overlay overlay_disable_imx219_agx_36x
compile_overlay overlay_disable_imx219_agx_35x

echo "Copying Auvidea binary DTBs..."
for f in "$DTS_DIR/auvidea"/*.dtb; do
    cp "$f" "$OUT_DIR/$(basename "$f")"
    echo "  copied $(basename "$f")"
done

echo "Done. DTBs in $OUT_DIR"
