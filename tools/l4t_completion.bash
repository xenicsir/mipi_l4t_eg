#!/bin/bash
#******************************************************************************
# l4t_completion.bash - Bash completion for L4T build scripts
#
# Installation:
#   Source in your .bashrc with the path to the configuration file:
#     . /path/to/l4t_completion.bash /path/to/eg_config.yaml
#
# Supported commands:
#   l4t_prepare.sh
#   l4t_copy_sources.sh
#   l4t_patch_sources.sh
#   l4t_build.sh
#   l4t_gen_delivery_package.sh
#   l4t_verify_packages.sh
#   l4t_build_all.sh
#   l4t_make.sh
#******************************************************************************

# Get configuration file from argument
_L4T_CONFIG_FILE="${1:-}"
_L4T_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_EGCFG="python3 $_L4T_SCRIPT_DIR/egcfg.py"

# Initialize completion variables from configuration file
_l4t_init_completion() {
    if [[ -n "$_L4T_CONFIG_FILE" ]] && [[ -f "$_L4T_CONFIG_FILE" ]]; then
        _l4t_versions=$($_EGCFG versions "$_L4T_CONFIG_FILE" 2>/dev/null)
        _l4t_vendors=$($_EGCFG vendors "$_L4T_CONFIG_FILE" 2>/dev/null)
        _l4t_carrier_boards=$($_EGCFG carriers "$_L4T_CONFIG_FILE" 2>/dev/null)
        _l4t_soms=$($_EGCFG soms "$_L4T_CONFIG_FILE" 2>/dev/null)
    fi
    # Fallback defaults if no configuration file
    _l4t_versions="${_l4t_versions:-32.7.1 32.7.4 32.7.5 32.7.6 35.1 35.3.1 35.4.1 35.5.0 35.6.0 35.6.1 35.6.2 35.6.4 36.4 36.4.3 36.4.4 36.5.0}"
    _l4t_vendors="${_l4t_vendors:-generic forecr}"
    _l4t_carrier_boards="${_l4t_carrier_boards:-generic dsboard_ornxs}"
    _l4t_soms="${_l4t_soms:-t210 t186}"
}

# Initialize on load
_l4t_init_completion

# Common completion function for l4t scripts
_l4t_common_completion() {
    local cur prev opts
    COMPREPLY=()
    cur="${COMP_WORDS[COMP_CWORD]}"
    prev="${COMP_WORDS[COMP_CWORD-1]}"

    # Base options for all l4t scripts
    local common_opts="-v --l4t-version -V --vendor -s --som -c --carrier-board -h --help"

    # Script-specific options
    local script_name=$(basename "${COMP_WORDS[0]}")
    local extra_opts=""

    case "$script_name" in
        l4t_build.sh)
            extra_opts="--standalone --no-verify-dtsi"
            ;;
        l4t_prepare.sh)
            extra_opts="--archive-dir"
            ;;
        l4t_gen_delivery_package.sh)
            extra_opts="-p --package-version --delivery-dir"
            ;;
        l4t_verify_packages.sh)
            # l4t_verify_packages.sh - version/vendor/carrier are optional filters
            extra_opts="--verbose --list"
            ;;
        l4t_build_all.sh)
            # l4t_build_all.sh has different options
            common_opts="-p --package-version --from-scratch --patches-only -h --help"
            ;;
        l4t_make.sh)
            # l4t_make.sh master orchestration script
            extra_opts="-p --package-version --standalone --no-verify-dtsi --archive-dir --delivery-dir --prepare --copy-sources --patch-sources --build --gen-package --from-scratch --abort-on-error --continue-on-error --dry-run --list"
            ;;
    esac

    opts="$common_opts $extra_opts"

    # Handle option arguments
    case "$prev" in
        -v|--l4t-version)
            COMPREPLY=( $(compgen -W "$_l4t_versions" -- "$cur") )
            return 0
            ;;
        -V|--vendor)
            COMPREPLY=( $(compgen -W "$_l4t_vendors" -- "$cur") )
            return 0
            ;;
        -s|--som)
            COMPREPLY=( $(compgen -W "$_l4t_soms" -- "$cur") )
            return 0
            ;;
        -c|--carrier-board)
            COMPREPLY=( $(compgen -W "$_l4t_carrier_boards" -- "$cur") )
            return 0
            ;;
        -p|--package-version)
            # Package version - no completion, user provides value
            return 0
            ;;
        --archive-dir|--delivery-dir)
            # Directory completion
            COMPREPLY=( $(compgen -d -- "$cur") )
            return 0
            ;;
    esac

    # Complete options if cur starts with -
    if [[ "$cur" == -* ]]; then
        COMPREPLY=( $(compgen -W "$opts" -- "$cur") )
        return 0
    fi

    # Default: complete with options
    COMPREPLY=( $(compgen -W "$opts" -- "$cur") )
    return 0
}

# Register completions for all l4t scripts
complete -F _l4t_common_completion l4t_prepare.sh
complete -F _l4t_common_completion l4t_copy_sources.sh
complete -F _l4t_common_completion l4t_patch_sources.sh
complete -F _l4t_common_completion l4t_build.sh
complete -F _l4t_common_completion l4t_gen_delivery_package.sh
complete -F _l4t_common_completion l4t_verify_packages.sh
complete -F _l4t_common_completion l4t_build_all.sh
complete -F _l4t_common_completion l4t_make.sh

# Also support calling scripts with ./
complete -F _l4t_common_completion ./l4t_prepare.sh
complete -F _l4t_common_completion ./l4t_copy_sources.sh
complete -F _l4t_common_completion ./l4t_patch_sources.sh
complete -F _l4t_common_completion ./l4t_build.sh
complete -F _l4t_common_completion ./l4t_gen_delivery_package.sh
complete -F _l4t_common_completion ./l4t_verify_packages.sh
complete -F _l4t_common_completion ./l4t_build_all.sh
complete -F _l4t_common_completion ./l4t_make.sh
