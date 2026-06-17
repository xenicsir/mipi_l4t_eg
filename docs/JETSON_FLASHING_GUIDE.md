# Jetson Orin NX / Nano — Flashing Usage Guide

Command reference for flashing / upgrading / downgrading Orin NX and Orin Nano boards
(NVIDIA devkit and Forecr DSBOARD-ORNXS) between **L4T 35.6.0** and **L4T 36.4.4**.

This guide lists *what to run*. The technical background (boot architecture, why a full
`flash.sh` is needed to downgrade, failure analysis, VM/USB issues) is intentionally left
out — keep this as a usage cheat-sheet.

---

## Reminders — boards not covered here

- **Jetson Nano (non-Orin) and Xavier NX** → follow **NVIDIA**'s recommendations.
- **AGX Orin on Auvidea X230D** → follow **Auvidea**'s recommendations.

---

## Host prerequisites (read first)

- Flash from a **bare-metal Linux host** — **not a VM, not WSL** (the USB recovery link
  drops mid-flash under virtualization).
- Install the prerequisites once: `sudo ./tools/l4t_flash_prerequisites.sh`
- Use a **direct USB-C cable** (no hub).
- Put the board in **recovery mode** (hold RECOVERY, tap RESET) **before each** command.
- All commands are run from the BSP's `Linux_for_Tegra/` directory.
- When using **SDK Manager**, use version **2.4.0** — some of the JetPack versions
  listed here are no longer offered in 2.4.1.

---

## NVIDIA devkit — Orin NX (P3767-0000, NVMe)

35.6.0 ↔ 36.4.4 with **SDK Manager 2.4.0** → OK

If using commands instead:

**35.6.0 → 36.4.4:**
```bash
sudo ./flash.sh jetson-orin-nano-devkit-nvme internal
```
or:
```bash
sudo ./tools/kernel_flash/l4t_initrd_flash.sh \
    --external-device nvme0n1p1 \
    -c tools/kernel_flash/flash_l4t_external.xml \
    -p "-c bootloader/generic/cfg/flash_t234_qspi.xml" \
    --showlogs --network usb0 \
    jetson-orin-nano-devkit internal
```

**36.4.4 → 35.6.0:**
```bash
sudo ./flash.sh jetson-orin-nano-devkit-nvme internal
```

---

## NVIDIA devkit — Orin Nano with SD card (P3767-0005)

35.6.0 ↔ 36.4.4 with **SDK Manager 2.4.0** → OK

If using commands instead:

**35.6.0 → 36.4.4:**
```bash
sudo ./flash.sh jetson-orin-nano-devkit mmcblk0p1
```

**36.4.4 → 35.6.0** (two commands):
```bash
sudo ./flash.sh jetson-orin-nano-devkit mmcblk0p1
```
then:
```bash
sudo ./tools/kernel_flash/l4t_initrd_flash.sh \
    --external-device mmcblk1p1 \
    -c tools/kernel_flash/flash_l4t_external.xml \
    -p "-c bootloader/t186ref/cfg/flash_t234_qspi.xml" \
    --showlogs --network usb0 \
    jetson-orin-nano-devkit internal
```

---

## Forecr DSBOARD-ORNXS — Orin Nano with SD card (P3767-0005)

SD-card config (not the default Forecr config, which ships with SSD).

### Install 35.6.0
<https://www.forecr.io/blogs/installation/jetpack-5-x-installation-for-dsboard-ornxs>

> **If the board currently runs a 36.x version, run this first:**
> ```bash
> sudo ./flash.sh jetson-orin-nano-devkit mmcblk1p1
> ```

Flash the SD card:
```bash
sudo ./tools/kernel_flash/l4t_initrd_flash.sh \
    --external-device mmcblk1p1 \
    -c tools/kernel_flash/flash_l4t_external.xml \
    -p "-c bootloader/t186ref/cfg/flash_t234_qspi.xml" \
    --showlogs --network usb0 \
    jetson-orin-nano-devkit internal
```

### Install 36.4.4
<https://www.forecr.io/blogs/installation/jetpack-6-x-installation-for-dsboard-ornxs>

Flash the SD card:
```bash
sudo ./tools/kernel_flash/l4t_initrd_flash.sh \
    --external-device mmcblk0p1 \
    -c tools/kernel_flash/flash_l4t_external.xml \
    -p "-c bootloader/generic/cfg/flash_t234_qspi.xml" \
    --showlogs --network usb0 \
    jetson-orin-nano-devkit internal
```

---

## Forecr DSBOARD-ORNXS — Orin NX (P3767-0000, SSD)

### Install 35.6.0
<https://www.forecr.io/blogs/installation/jetpack-5-x-installation-for-dsboard-ornxs>

> **If the board currently runs a 36.x version, use this:**
> ```bash
> sudo ./flash.sh jetson-orin-nano-devkit-nvme internal
> ```

Otherwise:
```bash
sudo ./tools/kernel_flash/l4t_initrd_flash.sh \
    --external-device nvme0n1p1 \
    -c tools/kernel_flash/flash_l4t_external.xml \
    -p "-c bootloader/t186ref/cfg/flash_t234_qspi.xml" \
    --showlogs --network usb0 \
    jetson-orin-nano-devkit internal
```

### Install 36.4.4
<https://www.forecr.io/blogs/installation/jetpack-6-x-installation-for-dsboard-ornxs>

Flash the SSD:
```bash
sudo ./tools/kernel_flash/l4t_initrd_flash.sh \
    --external-device nvme0n1p1 \
    -c tools/kernel_flash/flash_l4t_external.xml \
    -p "-c bootloader/generic/cfg/flash_t234_qspi.xml" \
    --showlogs --network usb0 \
    jetson-orin-nano-devkit internal
```

---

## Notes

- **SD downgrade (36.4.4 → 35.6.0):** after the `flash.sh … mmcblkXp1` step the board
  boots 35.x but **kernel-panics** (`Attempted to kill init! exitcode=0x00007f00`). This
  is **expected** — the following `l4t_initrd_flash.sh` step fixes it.
- The `35.x` external-device name is `mmcblk1p1`, the `36.x` one is `mmcblk0p1` — use the
  values exactly as listed above.

---

## Troubleshooting (quick)

| Symptom (host log) | Cause | Action |
|--------------------|-------|--------|
| `tegrarcm_v2 … Error: Return value 8` (~15 s into flash) | USB link dropped — **VM / USB hub** | Flash from bare-metal, direct USB-C, no hub |
| `ECID is` empty / `probing the target board failed` | Board not in recovery | Re-arm recovery (hold RECOVERY, tap RESET) and retry |
| `python: command not found` | Host prerequisites missing | `sudo ./tools/l4t_flash_prerequisites.sh` |
