#!/bin/bash
#******************************************************************************
# detect_board.sh - Comprehensive Jetson board detection
#
# Detects all Jetson SoM (System on Module) and carrier boards including:
# - Nvidia official boards (Nano, TX1/TX2, Xavier, Orin)
# - Forecr/Exosens boards (DSBOARD, MILBOARD, RAIBOARD)
# - Connect Tech boards (Photon, Rogue, Spacely, Orbitty)
# - Auvidea boards (X230D, JN30D, J120)
# - Antmicro boards (open-source designs)
#
# Returns:
#   0 - Board detected successfully
#   1 - Unable to detect board
#
# Usage:
#   ./detect_board.sh              # Print board type
#   ./detect_board.sh -v           # Verbose with details
#   ./detect_board.sh --json       # JSON output
#   ./detect_board.sh --short      # Short name only
#******************************************************************************

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Output mode
VERBOSE=0
JSON_OUTPUT=0
SHORT_NAME=0

# Parse arguments
while [[ $# -gt 0 ]]; do
    case "$1" in
        -v|--verbose) VERBOSE=1; shift ;;
        --json) JSON_OUTPUT=1; shift ;;
        --short) SHORT_NAME=1; shift ;;
        -h|--help)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Detects Jetson board type including SoM and carrier board."
            echo ""
            echo "Options:"
            echo "  -v, --verbose    Print detailed information"
            echo "  --json          Output in JSON format"
            echo "  --short         Print short board name only"
            echo "  -h, --help      Show this help"
            echo ""
            echo "Examples:"
            echo "  BOARD=\$(./detect_board.sh --short)"
            echo "  ./detect_board.sh --json | jq '.module'"
            exit 0
            ;;
        *) echo "Unknown option: $1" >&2; exit 1 ;;
    esac
done

#******************************************************************************
# Detect Jetson SoM (System on Module)
#******************************************************************************
detect_som() {
    local model="$1"
    local dtb="$2"
    local compatible="$3"
    local som="unknown"
    local som_pn=""
    local tegra=""

    # Detect Tegra SoC version (check compatible first, then dtb)
    if [[ "$compatible" =~ tegra234 ]] || [[ "$dtb" =~ tegra234|t234|t23x ]]; then
        tegra="t234"
    elif [[ "$compatible" =~ tegra194 ]] || [[ "$dtb" =~ tegra194|t194|t19x ]]; then
        tegra="t194"
    elif [[ "$compatible" =~ tegra186 ]] || [[ "$dtb" =~ tegra186|t186|t18x ]]; then
        tegra="t186"
    elif [[ "$compatible" =~ tegra210 ]] || [[ "$dtb" =~ tegra210|t210 ]]; then
        tegra="t210"
    fi

    # Detect specific SoM based on part numbers and model strings
    case "$tegra" in
        t234)
            # Orin family
            if [[ "$dtb" =~ p3701 ]] || [[ "$compatible" =~ p3701 ]]; then
                som="agx-orin"
                if [[ "$compatible" =~ p3701-0000 ]] || [[ "$dtb" =~ p3701-0000 ]]; then som_pn="P3701-0000 (32GB)"
                elif [[ "$compatible" =~ p3701-0004 ]] || [[ "$dtb" =~ p3701-0004 ]]; then som_pn="P3701-0004 (32GB)"
                elif [[ "$compatible" =~ p3701-0005 ]] || [[ "$dtb" =~ p3701-0005 ]]; then som_pn="P3701-0005 (64GB)"
                elif [[ "$compatible" =~ p3701-0008 ]] || [[ "$dtb" =~ p3701-0008 ]]; then som_pn="P3701-0008"
                else som_pn="P3701 (AGX Orin)"; fi
            elif [[ "$dtb" =~ p3767 ]] || [[ "$compatible" =~ p3767 ]]; then
                # Check compatible strings first for accurate part number detection
                if [[ "$compatible" =~ p3767-0003 ]] || [[ "$dtb" =~ p3767-0003 ]]; then
                    som="orin-nano"; som_pn="P3767-0003 (8GB)"
                elif [[ "$compatible" =~ p3767-0004 ]] || [[ "$dtb" =~ p3767-0004 ]]; then
                    som="orin-nano"; som_pn="P3767-0004 (4GB)"
                elif [[ "$compatible" =~ p3767-0005 ]] || [[ "$dtb" =~ p3767-0005 ]]; then
                    som="orin-nano"; som_pn="P3767-0005 (8GB)"
                elif [[ "$compatible" =~ p3767-0000 ]] || [[ "$dtb" =~ p3767-0000 ]]; then
                    som="orin-nx"; som_pn="P3767-0000 (16GB)"
                elif [[ "$compatible" =~ p3767-0001 ]] || [[ "$dtb" =~ p3767-0001 ]]; then
                    som="orin-nx"; som_pn="P3767-0001 (8GB)"
                elif [[ "$model" =~ "Orin Nano" ]]; then
                    som="orin-nano"; som_pn="P3767 (Orin Nano)"
                else
                    som="orin-nx"; som_pn="P3767 (Orin NX)"
                fi
            fi
            ;;
        t194)
            # Xavier family
            if [[ "$dtb" =~ p2888 ]] || [[ "$compatible" =~ p2888 ]]; then
                som="agx-xavier"
                if [[ "$compatible" =~ p2888-0001 ]] || [[ "$dtb" =~ p2888-0001 ]]; then som_pn="P2888-0001 (16GB)"
                elif [[ "$compatible" =~ p2888-0004 ]] || [[ "$dtb" =~ p2888-0004 ]]; then som_pn="P2888-0004 (32GB)"
                elif [[ "$compatible" =~ p2888-0005 ]] || [[ "$dtb" =~ p2888-0005 ]]; then som_pn="P2888-0005 (64GB)"
                elif [[ "$compatible" =~ p2888-0008 ]] || [[ "$dtb" =~ p2888-0008 ]]; then som_pn="P2888-0008 (Industrial)"
                else som_pn="P2888 (AGX Xavier)"; fi
            elif [[ "$dtb" =~ p3668 ]] || [[ "$compatible" =~ p3668 ]]; then
                som="xavier-nx"
                if [[ "$compatible" =~ p3668-0000 ]] || [[ "$dtb" =~ p3668-0000 ]]; then som_pn="P3668-0000 (8GB, SD)"
                elif [[ "$compatible" =~ p3668-0001 ]] || [[ "$dtb" =~ p3668-0001 ]]; then som_pn="P3668-0001 (8GB, eMMC)"
                elif [[ "$compatible" =~ p3668-0003 ]] || [[ "$dtb" =~ p3668-0003 ]]; then som_pn="P3668-0003 (16GB)"
                else som_pn="P3668 (Xavier NX)"; fi
            fi
            ;;
        t186)
            # TX2 family
            if [[ "$dtb" =~ p3310 ]] || [[ "$compatible" =~ p3310 ]]; then
                som="tx2"
                som_pn="P3310 (TX2 8GB)"
            elif [[ "$dtb" =~ p3489 ]] || [[ "$compatible" =~ p3489 ]]; then
                som="tx2i"
                som_pn="P3489 (TX2i Industrial)"
            elif [[ "$model" =~ "TX2" ]]; then
                som="tx2"
                som_pn="TX2"
            fi
            ;;
        t210)
            # Nano/TX1 family
            if [[ "$dtb" =~ p3448 ]] || [[ "$compatible" =~ p3448 ]]; then
                som="nano"
                if [[ "$compatible" =~ p3448-0000 ]] || [[ "$dtb" =~ p3448-0000 ]]; then som_pn="P3448-0000 (4GB, SD)"
                elif [[ "$compatible" =~ p3448-0002 ]] || [[ "$dtb" =~ p3448-0002 ]]; then som_pn="P3448-0002 (4GB, eMMC)"
                elif [[ "$compatible" =~ p3448-0003 ]] || [[ "$dtb" =~ p3448-0003 ]]; then som_pn="P3448-0003 (2GB)"
                else som_pn="P3448 (Nano)"; fi
            elif [[ "$dtb" =~ p2180 ]] || [[ "$compatible" =~ p2180 ]] || [[ "$model" =~ "TX1" ]]; then
                som="tx1"
                som_pn="P2180 (TX1)"
            elif [[ "$model" =~ "Nano" ]]; then
                som="nano"
                som_pn="Nano"
            fi
            ;;
    esac

    # Fallback to model string if not detected
    if [[ "$som" == "unknown" ]]; then
        if [[ "$model" =~ "AGX Orin" ]]; then som="agx-orin"
        elif [[ "$model" =~ "Orin NX" ]]; then som="orin-nx"
        elif [[ "$model" =~ "Orin Nano" ]]; then som="orin-nano"
        elif [[ "$model" =~ "AGX Xavier" ]]; then som="agx-xavier"
        elif [[ "$model" =~ "Xavier NX" ]]; then som="xavier-nx"
        elif [[ "$model" =~ "TX2" ]]; then som="tx2"
        elif [[ "$model" =~ "TX1" ]]; then som="tx1"
        elif [[ "$model" =~ "Nano" ]]; then som="nano"
        fi
    fi

    echo "$som|$som_pn|$tegra"
}

#******************************************************************************
# Detect carrier board
#******************************************************************************
detect_carrier() {
    local model="$1"
    local dtb="$2"
    local carrier="unknown"
    local carrier_pn=""
    local vendor="unknown"

    # Forecr/Exosens carrier boards
    if [[ "$dtb" =~ dsboard-ornxs || "$model" =~ "DSBOARD-ORNXS" ]]; then
        vendor="forecr"; carrier="dsboard-ornxs"; carrier_pn="DSBOARD-ORNXS (Orin Nano/NX compact)"
    elif [[ "$dtb" =~ dsboard-ornxlan || "$model" =~ "DSBOARD-ORNXLAN" ]]; then
        vendor="forecr"; carrier="dsboard-ornxlan"; carrier_pn="DSBOARD-ORNXLAN (Orin enhanced LAN)"
    elif [[ "$dtb" =~ dsboard-ornx || "$model" =~ "DSBOARD-ORNX" ]]; then
        vendor="forecr"; carrier="dsboard-ornx"; carrier_pn="DSBOARD-ORNX (Orin Nano/NX)"
    elif [[ "$dtb" =~ dsboard-nx2 || "$model" =~ "DSBOARD-NX2" ]]; then
        vendor="forecr"; carrier="dsboard-nx2"; carrier_pn="DSBOARD-NX2 (Xavier NX)"
    elif [[ "$dtb" =~ dsboard-xv2 || "$model" =~ "DSBOARD-XV2" ]]; then
        vendor="forecr"; carrier="dsboard-xv2"; carrier_pn="DSBOARD-XV2 (AGX Xavier/Orin)"
    elif [[ "$dtb" =~ dsboard-xv || "$model" =~ "DSBOARD-XV" ]]; then
        vendor="forecr"; carrier="dsboard-xv"; carrier_pn="DSBOARD-XV (AGX Xavier Industrial)"
    elif [[ "$dtb" =~ dsboard-agxmax || "$model" =~ "DSBOARD-AGXMAX" ]]; then
        vendor="forecr"; carrier="dsboard-agxmax"; carrier_pn="DSBOARD-AGXMAX (AGX Orin high-perf)"
    elif [[ "$dtb" =~ dsboard-agx || "$model" =~ "DSBOARD-AGX" ]]; then
        vendor="forecr"; carrier="dsboard-agx"; carrier_pn="DSBOARD-AGX (AGX Orin)"
    elif [[ "$dtb" =~ dsboard-thrmax || "$model" =~ "DSBOARD-THRMAX" ]]; then
        vendor="forecr"; carrier="dsboard-thrmax"; carrier_pn="DSBOARD-THRMAX (Jetson Thor)"
    elif [[ "$dtb" =~ milboard-agxmax || "$model" =~ "MILBOARD-AGXMAX" ]]; then
        vendor="forecr"; carrier="milboard-agxmax"; carrier_pn="MILBOARD-AGXMAX (Military high-perf)"
    elif [[ "$dtb" =~ milboard-agx || "$model" =~ "MILBOARD-AGX" ]]; then
        vendor="forecr"; carrier="milboard-agx"; carrier_pn="MILBOARD-AGX (Military/Defense)"
    elif [[ "$dtb" =~ milboard-ornx || "$model" =~ "MILBOARD-ORNX" ]]; then
        vendor="forecr"; carrier="milboard-ornx"; carrier_pn="MILBOARD-ORNX (Military Orin)"
    elif [[ "$dtb" =~ milboard-xv || "$model" =~ "MILBOARD-XV" ]]; then
        vendor="forecr"; carrier="milboard-xv"; carrier_pn="MILBOARD-XV (Military Xavier)"
    elif [[ "$dtb" =~ raiboard-agx || "$model" =~ "RAIBOARD-AGX" ]]; then
        vendor="forecr"; carrier="raiboard-agx"; carrier_pn="RAIBOARD-AGX (Railway EN50155)"
    elif [[ "$dtb" =~ raiboard-ornx || "$model" =~ "RAIBOARD-ORNX" ]]; then
        vendor="forecr"; carrier="raiboard-ornx"; carrier_pn="RAIBOARD-ORNX (Railway)"
    # Connect Tech carrier boards
    elif [[ "$model" =~ "Photon" ]] || [[ "$dtb" =~ "ngx003|ngx002" ]]; then
        vendor="connecttech"
        if [[ "$dtb" =~ "ngx002" ]]; then carrier="photon-poe"; carrier_pn="Photon NGX002 (with PoE)"
        else carrier="photon"; carrier_pn="Photon NGX003"; fi
    elif [[ "$model" =~ "Rogue" ]] || [[ "$dtb" =~ "agx202|agx111" ]]; then
        vendor="connecttech"
        if [[ "$dtb" =~ "agx202" ]]; then carrier="rogue-agx-orin"; carrier_pn="Rogue AGX202 (AGX Orin)"
        else carrier="rogue-agx-xavier"; carrier_pn="Rogue AGX111 (AGX Xavier)"; fi
    elif [[ "$model" =~ "Spacely" ]] || [[ "$dtb" =~ "asg006|asg026" ]]; then
        vendor="connecttech"; carrier="spacely"; carrier_pn="Spacely (TX2/TX1)"
    elif [[ "$model" =~ "Orbitty" ]]; then
        vendor="connecttech"; carrier="orbitty"; carrier_pn="Orbitty (TX2/TX1 compact)"
    # Auvidea carrier boards
    elif [[ "$model" =~ "X230D" ]] || [[ "$dtb" =~ "x230d" ]]; then
        vendor="auvidea"; carrier="x230d"; carrier_pn="X230D (AGX Orin)"
    elif [[ "$model" =~ "JN30D" ]] || [[ "$dtb" =~ "jn30d" ]]; then
        vendor="auvidea"; carrier="jn30d"; carrier_pn="JN30D (Nano/TX2 NX compact)"
    elif [[ "$model" =~ "J120" ]] || [[ "$dtb" =~ "j120" ]]; then
        vendor="auvidea"; carrier="j120"; carrier_pn="J120 (Industrial)"
    # Nvidia official carrier boards
    elif [[ "$dtb" =~ p3768 ]]; then
        vendor="nvidia"; carrier="p3768"; carrier_pn="P3768 (Orin Nano/NX DevKit)"
    elif [[ "$dtb" =~ p3509 ]]; then
        vendor="nvidia"; carrier="p3509"; carrier_pn="P3509 (Xavier/Orin NX)"
    elif [[ "$dtb" =~ p3737 ]]; then
        vendor="nvidia"; carrier="p3737"; carrier_pn="P3737 (AGX Orin DevKit)"
    elif [[ "$dtb" =~ p2822 ]]; then
        vendor="nvidia"; carrier="p2822"; carrier_pn="P2822 (AGX Xavier DevKit)"
    elif [[ "$dtb" =~ p3449 ]]; then
        vendor="nvidia"; carrier="p3449"; carrier_pn="P3449 (Nano DevKit)"
    elif [[ "$dtb" =~ p2597 ]]; then
        vendor="nvidia"; carrier="p2597"; carrier_pn="P2597 (TX1/TX2 DevKit)"
    elif [[ "$dtb" =~ e3900 ]]; then
        vendor="nvidia"; carrier="e3900"; carrier_pn="E3900 (AGX Xavier Industrial)"
    elif [[ "$dtb" =~ e3366 ]]; then
        vendor="nvidia"; carrier="e3366"; carrier_pn="E3366 (AGX Xavier Industrial)"
    elif [[ "$model" =~ "Developer Kit" ]] || [[ "$model" =~ "DevKit" ]]; then
        vendor="nvidia"; carrier="devkit"; carrier_pn="Developer Kit"
    fi

    echo "$vendor|$carrier|$carrier_pn"
}

#******************************************************************************
# Main detection function
#******************************************************************************
detect_board_type() {
    local model=""
    local dtb=""
    local compatible=""

    # Read device tree info
    if [[ -f /proc/device-tree/model ]]; then
        model=$(cat /proc/device-tree/model 2>/dev/null | tr -d '\0')
    fi

    if [[ -f /proc/device-tree/nvidia,dtsfilename ]]; then
        dtb=$(cat /proc/device-tree/nvidia,dtsfilename 2>/dev/null | tr -d '\0')
    fi

    if [[ -f /proc/device-tree/compatible ]]; then
        compatible=$(cat /proc/device-tree/compatible 2>/dev/null | tr '\0' ' ')
    fi

    # Detect SoM
    IFS='|' read -r som som_pn tegra <<< "$(detect_som "$model" "$dtb" "$compatible")"

    # Detect carrier
    IFS='|' read -r vendor carrier carrier_pn <<< "$(detect_carrier "$model" "$dtb")"

    # Construct board type
    local board_type=""
    if [[ "$vendor" == "forecr" ]]; then
        board_type="$carrier"
    elif [[ "$vendor" != "unknown" && "$vendor" != "nvidia" ]]; then
        board_type="$vendor-$carrier"
    elif [[ "$vendor" == "nvidia" ]]; then
        if [[ "$carrier" == "devkit" ]]; then
            board_type="nvidia-devkit"
        else
            board_type="nvidia-$carrier"
        fi
    else
        board_type="unknown"
    fi

    # Export for output
    export DETECTED_MODEL="$model"
    export DETECTED_DTB="$dtb"
    export DETECTED_COMPATIBLE="$compatible"
    export DETECTED_SOM="$som"
    export DETECTED_SOM_PN="$som_pn"
    export DETECTED_TEGRA="$tegra"
    export DETECTED_VENDOR="$vendor"
    export DETECTED_CARRIER="$carrier"
    export DETECTED_CARRIER_PN="$carrier_pn"
    export DETECTED_BOARD_TYPE="$board_type"

    [[ "$board_type" != "unknown" ]] && return 0 || return 1
}

#******************************************************************************
# Output functions
#******************************************************************************
print_board_info() {
    if [[ $JSON_OUTPUT -eq 1 ]]; then
        cat <<EOF
{
  "board_type": "$DETECTED_BOARD_TYPE",
  "vendor": "$DETECTED_VENDOR",
  "som": {
    "type": "$DETECTED_SOM",
    "part_number": "$DETECTED_SOM_PN",
    "tegra": "$DETECTED_TEGRA"
  },
  "carrier": {
    "type": "$DETECTED_CARRIER",
    "description": "$DETECTED_CARRIER_PN"
  },
  "model": "$DETECTED_MODEL",
  "dtb": "$DETECTED_DTB"
}
EOF
    elif [[ $SHORT_NAME -eq 1 ]]; then
        echo "$DETECTED_BOARD_TYPE"
    elif [[ $VERBOSE -eq 1 ]]; then
        echo -e "${BLUE}=== Jetson Board Detection ===${NC}"
        echo ""
        echo -e "${GREEN}Board Type:${NC} $DETECTED_BOARD_TYPE"
        echo ""
        echo -e "${GREEN}System on Module (SoM):${NC}"
        echo "  Type: $DETECTED_SOM"
        echo "  Part: $DETECTED_SOM_PN"
        echo "  SoC:  $DETECTED_TEGRA"
        echo ""
        echo -e "${GREEN}Carrier Board:${NC}"
        echo "  Vendor: $DETECTED_VENDOR"
        echo "  Type:   $DETECTED_CARRIER"
        echo "  Desc:   $DETECTED_CARRIER_PN"
        echo ""
        echo -e "${GREEN}Device Tree:${NC}"
        echo "  Model: $DETECTED_MODEL"
        if [[ -n "$DETECTED_DTB" ]]; then
            echo "  DTB:   $DETECTED_DTB"
        fi
        if [[ -n "$DETECTED_COMPATIBLE" ]]; then
            echo "  Compatible: $DETECTED_COMPATIBLE"
        fi
    else
        echo "$DETECTED_BOARD_TYPE"
    fi
}

#******************************************************************************
# Main
#******************************************************************************

if ! detect_board_type; then
    if [[ $JSON_OUTPUT -eq 1 ]]; then
        echo '{"error": "Unable to detect board type"}'
    else
        echo "unknown"
    fi
    exit 1
fi

print_board_info
exit 0
