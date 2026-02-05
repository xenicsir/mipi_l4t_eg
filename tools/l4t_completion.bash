#!/bin/bash
#******************************************************************************
# l4t_completion.bash - Bash completion for L4T build scripts
#
# Installation:
#   Option 1: Source in your .bashrc
#     echo 'source /path/to/l4t_completion.bash' >> ~/.bashrc
#
#   Option 2: Install system-wide
#     sudo cp l4t_completion.bash /etc/bash_completion.d/l4t
#
#   Option 3: Temporary (current shell only)
#     source /path/to/l4t_completion.bash
#
# Supported commands:
#   l4t_prepare.sh
#   l4t_copy_sources.sh
#   l4t_patch_sources.sh
#   l4t_build.sh
#   l4t_gen_delivery_package.sh
#   l4t_build_all.sh
#******************************************************************************

# L4T versions supported
_l4t_versions="32.7.1 32.7.4 32.7.5 32.7.6 35.1 35.3.1 35.4.1 35.5.0 35.6.0 35.6.1 35.6.2 36.4 36.4.3 36.4.4"

# Vendors and their supported carrier boards
_l4t_vendors="generic forecr"
_l4t_carrier_boards_generic="generic"
_l4t_carrier_boards_forecr="dsboard_ornx"

# Get carrier boards for a vendor
_l4t_get_carrier_boards() {
    local vendor="$1"
    case "$vendor" in
        generic)
            echo "$_l4t_carrier_boards_generic"
            ;;
        forecr)
            echo "$_l4t_carrier_boards_forecr"
            ;;
        *)
            echo "generic"
            ;;
    esac
}

# Common completion function for l4t scripts
_l4t_common_completion() {
    local cur prev opts
    COMPREPLY=()
    cur="${COMP_WORDS[COMP_CWORD]}"
    prev="${COMP_WORDS[COMP_CWORD-1]}"

    # Base options for all l4t scripts
    local common_opts="-v --l4t-version -V --vendor -c --carrier-board -h --help"

    # Script-specific options
    local script_name=$(basename "${COMP_WORDS[0]}")
    local extra_opts=""

    case "$script_name" in
        l4t_build.sh)
            extra_opts="-s --standalone"
            ;;
        l4t_gen_delivery_package.sh)
            extra_opts="-p --package-version"
            ;;
        l4t_build_all.sh)
            # l4t_build_all.sh has different options
            common_opts="-p --package-version --from-scratch --patches-only -h --help"
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
        -c|--carrier-board)
            # Find the vendor in the command line to provide appropriate carrier boards
            local vendor="generic"
            local i
            for ((i=1; i<COMP_CWORD; i++)); do
                case "${COMP_WORDS[i]}" in
                    -V|--vendor)
                        vendor="${COMP_WORDS[i+1]}"
                        break
                        ;;
                esac
            done
            local carrier_boards=$(_l4t_get_carrier_boards "$vendor")
            COMPREPLY=( $(compgen -W "$carrier_boards" -- "$cur") )
            return 0
            ;;
        -p|--package-version)
            # Package version - no completion, user provides value
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
complete -F _l4t_common_completion l4t_build_all.sh

# Also support calling scripts with ./
complete -F _l4t_common_completion ./l4t_prepare.sh
complete -F _l4t_common_completion ./l4t_copy_sources.sh
complete -F _l4t_common_completion ./l4t_patch_sources.sh
complete -F _l4t_common_completion ./l4t_build.sh
complete -F _l4t_common_completion ./l4t_gen_delivery_package.sh
complete -F _l4t_common_completion ./l4t_build_all.sh
