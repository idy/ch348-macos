#ifndef CH348_RING_H
#define CH348_RING_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Indices are monotonic uint32_t counters with unsigned overflow. Mask only
 * physical byte offsets into the power-of-two ring, which has one empty slot.
 * Synchronization and publishing the returned index belong to the caller. */
int ch348_ring_peek(const uint8_t *ring, uint32_t size, uint32_t producer,
                    uint32_t consumer, uint8_t *out, uint32_t capacity,
                    uint32_t *out_count);
/* Returns 1 on full, -1 on invalid input, 0 after copying the complete input. */
int ch348_ring_append(uint8_t *ring, uint32_t size, uint32_t producer,
                      uint32_t consumer, const uint8_t *data, uint32_t length,
                      uint32_t *out_producer);

#ifdef __cplusplus
}
#endif
#endif
