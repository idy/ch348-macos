#ifndef CH348_PROTOCOL_H
#define CH348_PROTOCOL_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define CH348_PORT_COUNT 8u
#define CH348_RX_RECORD_SIZE 32u
#define CH348_RX_DATA_SIZE 30u
#define CH348_CONFIG_SIZE 12u
#define CH348_UPLOAD_MODE_SIZE 8u

typedef int (*ch348_receive_fn)(void *user, unsigned port,
                                const uint8_t *data, size_t size);

/* Original encoders for the published CH348 wire protocol; no vendor code. */
size_t ch348_encode_upload_mode(uint8_t out[CH348_UPLOAD_MODE_SIZE],
                                uint8_t chip_version);
int ch348_encode_config(uint8_t out[CH348_CONFIG_SIZE], unsigned port,
                        uint32_t baud, unsigned data_bits,
                        unsigned stop_bits, unsigned parity);
size_t ch348_encode_transmit(uint8_t *out, size_t capacity, unsigned port,
                             const uint8_t *data, size_t size);
int ch348_decode_receive(const uint8_t *data, size_t size,
                         ch348_receive_fn receive, void *user);
int ch348_decode_status(const uint8_t *data, size_t size,
                        uint8_t *out_empty_ports);
uint8_t ch348_register(unsigned port, uint8_t reg);

#ifdef __cplusplus
}
#endif

#endif
