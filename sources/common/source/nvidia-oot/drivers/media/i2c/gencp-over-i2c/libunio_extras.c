/*
 *
 * Copyright (c) 2026, Xenics Exosens, All Rights Reserved.
 *
 */
#include "libunio_extras.h"

#define PREFIX "libunio_extra"
#include "liblogger.h"

// Initialize the buffer
void rb_init(struct ring_buffer *rb)
{
    // TODO: update to dynamic array
    rb->head = 0;
    rb->tail = 0;
    rb->count = 0;
}

// Flush the buffer
void rb_flush(struct ring_buffer *rb)
{
    //No need to clear the array, just the index pointers
    rb->head = 0;
    rb->tail = 0;
    rb->count = 0;
}

// Check if the buffer is empty
bool rb_is_empty(struct ring_buffer *rb)
{
    return rb->count == 0;
}

// Check if the buffer is full
bool rb_is_full(struct ring_buffer *rb)
{
    return rb->count >= BUFFER_SIZE; // TODO: overflow check?
}

// Add an element to the buffer
int rb_push(struct ring_buffer *rb, u8 value)
{
    if (rb_is_full(rb)) {
        return -1; // buffer full
    }
    rb->data[rb->head] = value;
    rb->head = (rb->head + 1) & (BUFFER_SIZE - 1); // wrap around mask
    rb->count++;
    return 0;
}

// Remove an element from the buffer
int rb_pop(struct ring_buffer *rb, u8 *value)
{
    if (rb_is_empty(rb)) {
        return -1; // buffer empty
    }
    *value = rb->data[rb->tail];
    rb->tail = (rb->tail + 1) & (BUFFER_SIZE - 1); // wrap around mask
    rb->count--;
    return 0;
}

int parse_gencp_raw(u8 *buff, size_t buff_len, struct ring_buffer *rb)
{
    static u8 last_byte = 0xAA;
    static int word_count = 0;

    for (size_t i = 0; i < buff_len; i++){
        if(buff[i] != last_byte) { // ignore the duplicates
            word_count++;
            // XOR the two byte to check if they are the inverse of eachother
            if((buff[i] ^ last_byte) == 0xff) {
                if (word_count > 1) {
                    word_count = 0;
                    int ret;
                    ret = rb_push(rb, last_byte);
                    PRINT_DEBUG("Parsed: 0x%x\n", last_byte);
                    if (ret < 0) return -1;
                }
            }
        }
        last_byte = buff[i];
    }
    return 0;
}
