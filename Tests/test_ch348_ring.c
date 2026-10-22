#include "ch348_ring.h"
#include <assert.h>
#include <string.h>

int main(void) {
    uint8_t ring[8] = {0};
    const uint8_t input[] = {0, 0xff, 0x11, 0x13, 4, 5, 6};
    uint8_t output[8];
    uint32_t producer, count;
    assert(ch348_ring_append(ring, 8, 6, 6, input, 7, &producer) == 0);
    assert(producer == 5);
    assert(ch348_ring_peek(ring, 8, producer, 6, output, 8, &count) == 0);
    assert(count == 7 && memcmp(input, output, 7) == 0);
    uint8_t before[8]; memcpy(before, ring, 8);
    assert(ch348_ring_append(ring, 8, producer, 6, input, 1, &producer) == 1);
    assert(producer == 5 && memcmp(before, ring, 8) == 0);
    assert(ch348_ring_peek(ring, 8, 5, 6, output, 2, &count) == 0 && count == 2);
    assert(ch348_ring_peek(ring, 7, 0, 0, output, 8, &count) == -1 && count == 0);
    assert(ch348_ring_peek(ring, 8, 8, 0, output, 8, &count) == -1);
    assert(ch348_ring_append(ring, 8, 0, 8, input, 1, &producer) == -1);
    uint32_t consumer = 0;
    producer = 0;
    for (unsigned iteration = 0; iteration < 10000; ++iteration) {
        const uint32_t length = iteration % 7u + 1u;
        assert(ch348_ring_append(ring, 8, producer, consumer, input, length, &producer) == 0);
        assert(ch348_ring_peek(ring, 8, producer, consumer, output, 8, &count) == 0);
        assert(count == length && memcmp(input, output, length) == 0);
        consumer = producer;
    }
    return 0;
}
