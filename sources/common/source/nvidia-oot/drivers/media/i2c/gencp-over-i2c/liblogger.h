/*
 *
 * Copyright (c) 2026, Xenics Exosens, All Rights Reserved.
 *
 */
#ifndef LIB_LOGGER_H
#define LIB_LOGGER_H

#define LOG_INFO
// #define LOG_DEBUG
#define LOG_ERROR

#ifndef PREFIX
    #define PREFIX "liblogger"
#endif

#ifdef __KERNEL__
    #include <linux/kernel.h>
#else
    #include <stdio.h> //for printf
#endif


// Info log declaration
#ifdef LOG_INFO
    #ifdef __KERNEL__
        #define PRINT_INFO(fmt, ...) pr_info(PREFIX ": [INFO]-> " fmt, ##__VA_ARGS__)
    #else
        #define PRINT_INFO(fmt, ...) printf(PREFIX ": [INFO]-> " fmt, ##__VA_ARGS__)
    #endif
#else
    #define PRINT_INFO(fmt, ...) ((void)0)
#endif

// Debug log declaration
// WARNING: #define DEBUG has to be defined for pr_debug to work in kernel.
// It should be defined before the kernel.h is included.
// OR in the make add the following: EXTRA_CFLAGS="-DDEBUG -g -O0"
// TODO: Implement this using CONFIG_DYNAMIC_DEBUG instead? IDK, needs more research
#ifdef LOG_DEBUG
    #ifdef __KERNEL__
        #define PRINT_DEBUG(fmt, ...) pr_debug(PREFIX ": [DEBUG]-> " fmt, ##__VA_ARGS__)
    #else
        #define PRINT_DEBUG(fmt, ...) printf(PREFIX ": [DEBUG]-> " fmt, ##__VA_ARGS__)
    #endif
#else
    #define PRINT_DEBUG(fmt, ...) ((void)0)
#endif

// Error log declaration
#ifdef LOG_ERROR
    #ifdef __KERNEL__
        #define PRINT_ERROR(fmt, ...) pr_err(PREFIX ": [ERROR]-> " fmt, ##__VA_ARGS__)
    #else
        #define PRINT_ERROR(fmt, ...) printf(PREFIX ": [ERROR]-> " fmt, ##__VA_ARGS__)
    #endif
#else
    #define PRINT_ERROR(fmt, ...) ((void)0)
#endif

#endif /* LIB_LOGGER_H */
