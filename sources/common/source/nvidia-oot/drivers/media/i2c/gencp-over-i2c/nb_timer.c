/*
 *
 * Copyright (c) 2026, Xenics Exosens, All Rights Reserved.
 *
 */
#include "nb_timer.h"

#define PREFIX "libunio"
#include "liblogger.h"

// Memory allocation calls
#ifdef __KERNEL__ // automatically defined when building kernel modules
    #include <linux/timer.h>
#else
    #include <string.h>
    #define timer_setup(...) ((void)0) //ignore the timer setup function from kernel target
    #define mod_timer (...) ((void)0) //ignore
    #define del_timer (ptr, ...) ((void)0) //ignore
    #define NSECS_TO_MSECS(ns) ((ns) / 1000000)
    #define  SECS_TO_MSECS(s)  ((s) * 1000)
#endif

struct timer_def *_timer_array_ptr;
size_t _timer_array_len;

#ifdef __KERNEL__
static void _timer_callback (struct timer_list *t){
    struct timer_def *timer_ptr = from_timer(timer_ptr, t, timer); // similar to container_of macro
    timer_ptr->done = 1;
    timer_ptr->active = 0;
    PRINT_DEBUG("Timer_triggered #%d\n", timer_ptr->id);

}
#endif

int nb_timers_init(int num_timers) {
    _timer_array_ptr = MEM_ALLOC(sizeof(struct timer_def) * num_timers);
    _timer_array_len = (size_t)num_timers;

    if (!_timer_array_ptr)
        return -1;

    for(int i=0; i<num_timers; i++){
        _timer_array_ptr->id = i;
        timer_setup(&_timer_array_ptr[i].timer, _timer_callback, 0);
    }
    return 0;
}

int nb_timer_start(int timer_id, int timer_dur_ms) {
    struct timer_def *timer_ptr = &_timer_array_ptr[timer_id];
    if (!timer_ptr) {
        PRINT_ERROR("Timer id#%d doesn't exist\n", timer_id);
        return -1;
    } else {
        PRINT_DEBUG("Starting timer id#%d for %dms\n", timer_id, timer_dur_ms);
        timer_ptr->active = 1;
        #ifdef __KERNEL__
            timer_ptr->done = 0;
            mod_timer(&timer_ptr->timer, jiffies + msecs_to_jiffies(timer_dur_ms));
        #else
            timer_ptr->duration_msec = timer_dur_ms;
            clock_gettime(CLOCK_MONOTONIC, &timer_ptr->start_time);
            PRINT_DEBUG("Start timer at %u msec", NSECS_TO_MSECS(timer_ptr->start_time.tv_nsec));
        #endif
        return 0;
    }
}

int nb_timer_is_expired(int timer_id) {
    struct timer_def *timer_ptr = &_timer_array_ptr[timer_id];
    #ifdef __KERNEL__
        return timer_ptr->done;
    #else
        struct timespec current_time;
        clock_gettime(CLOCK_MONOTONIC, &current_time);
        double elapsed =
            SECS_TO_MSECS(current_time.tv_sec - timer_ptr->start_time.tv_sec) +
            NSECS_TO_MSECS(current_time.tv_nsec - timer_ptr->start_time.tv_nsec);
        PRINT_DEBUG("Time elapsed, %d msec", elapsed);
        return (elapsed > timer_ptr->duration_msec);
    #endif
}

int nb_timer_delete(int timer_id) {
    struct timer_def *timer_ptr = &_timer_array_ptr[timer_id];
    if (!timer_ptr) {
        PRINT_ERROR("Timer id#%d doesn't exist\n", timer_id);
        return -1;
    } else {
        PRINT_DEBUG("Deleting timer id#%d\n", timer_id);
        #ifdef __KERNEL__
        del_timer(&timer_ptr->timer);
        #endif
        memset(timer_ptr, 0, sizeof(struct timer_def)); // not really required
        return 0;
    }
}

int nb_timer_delete_all (void) {
    for (size_t i = 0; i < _timer_array_len;i++){
        nb_timer_delete(i);
    }
    MEM_FREE(_timer_array_ptr);
    return 0;
}
