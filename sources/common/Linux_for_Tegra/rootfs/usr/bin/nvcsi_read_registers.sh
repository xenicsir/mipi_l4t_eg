while true;do echo DT:$(busybox devmem 0x15A101e0) WC:$(busybox devmem 0x15A101dc) CRC:$(busybox devmem 0x15A101d8) ERROR_STATUS:$(busybox devmem 0x15A101e8);done

