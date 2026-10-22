#include "ch348_ring.h"

static int valid(uint32_t size, uint32_t producer, uint32_t consumer) {
    return size >= 2u && (size & (size - 1u)) == 0u &&
           producer < size && consumer < size;
}

int ch348_ring_peek(const uint8_t *ring, uint32_t size, uint32_t producer,
                    uint32_t consumer, uint8_t *out, uint32_t capacity,
                    uint32_t *out_count) {
    if (out_count != NULL) *out_count = 0u;
    if (!ring || !out || !out_count || !valid(size, producer, consumer)) return -1;
    uint32_t count = (producer - consumer) & (size - 1u);
    if (count > capacity) count = capacity;
    for (uint32_t index = 0; index < count; ++index)
        out[index] = ring[(consumer + index) & (size - 1u)];
    *out_count = count;
    return 0;
}

int ch348_ring_append(uint8_t *ring, uint32_t size, uint32_t producer,
                      uint32_t consumer, const uint8_t *data, uint32_t length,
                      uint32_t *out_producer) {
    if (out_producer != NULL) *out_producer = producer;
    if (!ring || !data || !out_producer || !valid(size, producer, consumer)) return -1;
    const uint32_t free = (consumer - producer - 1u) & (size - 1u);
    if (length > free) return 1;
    for (uint32_t index = 0; index < length; ++index)
        ring[(producer + index) & (size - 1u)] = data[index];
    *out_producer = (producer + length) & (size - 1u);
    return 0;
}
