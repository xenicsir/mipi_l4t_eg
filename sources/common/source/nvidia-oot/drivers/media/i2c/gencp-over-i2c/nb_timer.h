/*
 *
 * Copyright (c) 2026, Xenics Exosens, All Rights Reserved.
 *
 */
#include "libtarget.h"

#ifdef __KERNEL__ // automatically defined when building kernel modules
    #include <linux/timer.h>
#else
    #include <time.h>
#endif

struct timer_def {
    int  id;
    int  active;
#ifdef __KERNEL__
    struct timer_list timer;
    int  done;
#else
    struct timespec start_time;
    double duration_msec;
#endif
};

int nb_timers_init(int num_timers);

int nb_timer_start(int timer_id, int timer_dur_ms);

int nb_timer_is_expired(int timer_id);

int nb_timer_delete(int timer_id);

int nb_timer_delete_all (void);
