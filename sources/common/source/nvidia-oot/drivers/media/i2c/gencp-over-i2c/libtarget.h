/*
 *
 * Copyright (c) 2026, Xenics Exosens, All Rights Reserved.
 *
 */
#ifndef LIB_PLATFORM_H
#define LIB_PLATFORM_H

// Data types
#ifdef __KERNEL__ // automatically defined when building kernel modules
    #include <linux/types.h>
    typedef u8  uint8_t;
    typedef u16 uint16_t;
    typedef u32 uint32_t;
    typedef u64 uint64_t;
#else
    #include <stdint.h>
    #include <stdbool.h>
    #include <stddef.h>
    #include <string.h>
    typedef uint8_t  u8;
    typedef uint16_t u16;
    typedef uint32_t u32;
    typedef uint64_t u64;
#endif


// Allocation of memories
#ifdef __KERNEL__ // automatically defined when building kernel modules
    #include <linux/slab.h>
    #define MEM_ALLOC(size) kzalloc(size, GFP_KERNEL)
    #define MEM_FREE(ptr) kfree(ptr)
#else
    #include <stdlib.h>
    #define MEM_ALLOC(size) malloc(size)
    #define MEM_FREE(ptr) free(ptr)
#endif

#endif /* LIB_PLATFORM_H */
