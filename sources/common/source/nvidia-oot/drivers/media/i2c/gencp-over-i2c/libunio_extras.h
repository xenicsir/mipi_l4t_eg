/*
 *
 * Copyright (c) 2026, Xenics Exosens, All Rights Reserved.
 *
 */
#ifndef LIB_UNIO_EXTRA_H
#define LIB_UNIO_EXTRA_H

#include "libtarget.h"

#define BUFFER_SIZE 8  // must be a power of two

struct ring_buffer {
    u8 data[BUFFER_SIZE];
    size_t head;  // write index
    size_t tail;  // read index
    size_t count;
};

enum return_status {
    ERROR = -1,
    SUCCESS = 0,
    NO_DATA = 1
};

// Initialize the buffer
void rb_init(struct ring_buffer *rb);

// Flush the buffer
void rb_flush(struct ring_buffer *rb);

// Check if the buffer is empty
bool rb_is_empty(struct ring_buffer *rb);

// Check if the buffer is full
bool rb_is_full(struct ring_buffer *rb);

// Add an element to the buffer
int rb_push(struct ring_buffer *rb, u8 value);

// Remove an element from the buffer
int rb_pop(struct ring_buffer *rb, u8 *value);

int parse_gencp_raw(u8 *buff, size_t buff_len, struct ring_buffer *rb);

#endif /* LIB_UNIO_EXTRA_H */
