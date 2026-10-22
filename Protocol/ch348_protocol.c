#include "ch348_protocol.h"

#include <string.h>

int ch348_encode_config(uint8_t out[CH348_CONFIG_SIZE], unsigned port,
                        uint32_t baud, unsigned data_bits,
                        unsigned stop_bits, unsigned parity) {
  if (out == NULL || port >= CH348_PORT_COUNT || baud < 1200u ||
      baud > 6000000u || data_bits < 5u || data_bits > 8u ||
      (stop_bits != 1u && stop_bits != 2u) || parity > 2u) {
    return -1;
  }
  /* The optional rotation and XOR fields are both zero (identity encoding). */
  const uint32_t receive_timeout = 150000u / baud + 1u;
  const uint8_t bytes[CH348_CONFIG_SIZE] = {
      (uint8_t)(0x90u | port), 0xa1u, (uint8_t)port,
      (uint8_t)(baud >> 24u), (uint8_t)(baud >> 16u),
      (uint8_t)(baud >> 8u), (uint8_t)baud,
      stop_bits == 2u ? 2u : 0u, (uint8_t)parity, (uint8_t)data_bits,
      (uint8_t)(receive_timeout < 5u ? 5u : receive_timeout), 0u,
  };
  memcpy(out, bytes, sizeof(bytes));
  return 0;
}

size_t ch348_encode_transmit(uint8_t *out, size_t capacity, unsigned port,
                             const uint8_t *data, size_t size) {
  if (out == NULL || data == NULL || port >= CH348_PORT_COUNT ||
      size == 0u || size > UINT16_MAX || capacity < 3u ||
      size > capacity - 3u) {
    return 0u;
  }
  out[0] = (uint8_t)port;
  out[1] = (uint8_t)size;
  out[2] = (uint8_t)(size >> 8u);
  memcpy(out + 3u, data, size);
  return size + 3u;
}

int ch348_decode_receive(const uint8_t *data, size_t size,
                         ch348_receive_fn receive, void *user) {
  if (data == NULL || receive == NULL || size % CH348_RX_RECORD_SIZE != 0u) {
    return -1;
  }
  /* Validate the complete USB transfer before delivering any of it. */
  for (size_t offset = 0u; offset < size; offset += CH348_RX_RECORD_SIZE) {
    if (data[offset] >= CH348_PORT_COUNT ||
        data[offset + 1u] > CH348_RX_DATA_SIZE) {
      return -1;
    }
  }
  for (size_t offset = 0u; offset < size; offset += CH348_RX_RECORD_SIZE) {
    const size_t count = data[offset + 1u];
    if (count != 0u &&
        receive(user, data[offset], data + offset + 2u, count) != 0) {
      return -1;
    }
  }
  return 0;
}

int ch348_decode_status(const uint8_t *data, size_t size,
                        uint8_t *out_empty_ports) {
  uint8_t empty_ports = 0u;
  if (data == NULL || out_empty_ports == NULL) {
    return -1;
  }
  *out_empty_ports = 0u;
  for (size_t offset = 0u; offset < size;) {
    if (size - offset < 3u || (data[offset] & 0x0fu) >= CH348_PORT_COUNT) {
      return -1;
    }
    const unsigned port = data[offset] & 0x0fu;
    const uint8_t reg = data[offset + 1u];
    size_t count = 3u;
    if (reg == 0xa1u) {
      count = 12u;
    } else if (reg >= 0x97u && reg <= 0x9du) {
      count = 4u;
    } else if (reg >= 0xa3u && reg <= 0xa7u) {
      count = reg == 0xa7u ? 10u : 3u;
    } else if ((reg & 0x0fu) == 0x02u) {
      empty_ports |= (uint8_t)(1u << port);
    }
    if (count > size - offset) {
      return -1;
    }
    offset += count;
  }
  *out_empty_ports = empty_ports;
  return 0;
}

uint8_t ch348_register(unsigned port, uint8_t reg) {
  return (uint8_t)(reg + (port % 4u) * 0x10u + (port >= 4u ? 8u : 0u));
}
