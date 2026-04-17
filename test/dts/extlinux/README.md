# extlinux.conf state templates

Used by Phase 1 + Phase 2 + Phase 3 tests to exercise every extlinux.conf state the
script / postinst can encounter. `{FDT}` is substituted with the absolute path to the
test's base DTB.

| State | File | What it simulates | What it exercises |
|---|---|---|---|
| `fresh` | `fresh.conf` | Freshly-flashed board, only `LABEL primary` | Happy path — extlinux has a resolvable LABEL primary, `_primary_dtb` is populated |
| `previously_eg` | `previously_eg.conf` | Board already configured with EG cams — `LABEL JetsonIO` present | Upgrade install path — `/proc/device-tree` reflects post-merge user-custom.dtb (no IMX219 dirs), script MUST re-detect IMX219 from the kernel DTB via `_primary_dtb` |
| `no_primary` | `no_primary.conf` | Unusual extlinux.conf without `LABEL primary` | Robustness — `_primary_dtb` is empty, script falls back to `/proc/device-tree`-only detection |
| `empty` | *(file absent)* | extlinux.conf completely missing | Robustness — `awk` on missing file returns empty, `_primary_dtb` is empty |

All 4 states run for every (version, platform_id, vendor) × every (port, camera) combo.
That means for each matrix entry, the script is invoked 4 × N<sub>ports</sub> × 7<sub>cams</sub>
times — catching regressions where a code path works in one state but not another.
