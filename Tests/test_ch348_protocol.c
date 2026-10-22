#include "ch348_protocol.h"

#include <assert.h>
#include <string.h>

typedef struct received {
  unsigned calls;
  uint8_t bytes[CH348_PORT_COUNT][CH348_RX_DATA_SIZE];
  size_t sizes[CH348_PORT_COUNT];
} received_t;

static int receive(void *user, unsigned port, const uint8_t *data, size_t size) {
  received_t *received = user;
  ++received->calls;
  assert(port < CH348_PORT_COUNT);
  assert(size <= sizeof(received->bytes[port]));
  memcpy(received->bytes[port], data, size);
  received->sizes[port] = size;
  return 0;
}

static void test_configuration(void) {
  uint8_t upload[CH348_UPLOAD_MODE_SIZE];
  const uint8_t upload_expected[] = {0x90, 0x9d, 1, 0, 0, 0, 0, 0};
  assert(ch348_encode_upload_mode(upload, 0x89) == 0u);
  assert(ch348_encode_upload_mode(NULL, 0x90) == 0u);
  assert(ch348_encode_upload_mode(upload, 0x8a) == sizeof(upload));
  assert(memcmp(upload, upload_expected, sizeof(upload)) == 0);
  memset(upload, 0xff, sizeof(upload));
  assert(ch348_encode_upload_mode(upload, 0x90) == sizeof(upload));
  assert(memcmp(upload, upload_expected, sizeof(upload)) == 0);
  uint8_t config[CH348_CONFIG_SIZE];
  const uint8_t expected[] = {
      0x97, 0xa1, 7, 0, 7, 8, 0, 0, 0, 8, 5, 0,
  };
  assert(ch348_encode_config(config, 7u, 460800u, 8u, 1u, 0u) == 0);
  assert(memcmp(config, expected, sizeof(expected)) == 0);
  assert(ch348_encode_config(config, 8u, 460800u, 8u, 1u, 0u) != 0);
  assert(ch348_encode_config(config, 0u, 0u, 8u, 1u, 0u) != 0);
  assert(ch348_encode_config(config, 0u, 6000001u, 8u, 1u, 0u) != 0);
  assert(ch348_encode_config(config, 0u, 9600u, 9u, 1u, 0u) != 0);
  assert(ch348_encode_config(config, 0u, 9600u, 8u, 3u, 0u) != 0);
  assert(ch348_encode_config(config, 0u, 9600u, 8u, 1u, 3u) != 0);
  assert(ch348_encode_config(config, 0u, 1200u, 7u, 2u, 2u) == 0);
  assert(config[7] == 2u && config[8] == 2u && config[9] == 7u);
  assert(config[10] == 126u);
  assert(ch348_register(3u, 1u) == 0x31u);
  assert(ch348_register(4u, 1u) == 0x09u);
  assert(ch348_register(7u, 4u) == 0x3cu);
}

static void test_transmit(void) {
  uint8_t input[509];
  uint8_t output[512];
  for (size_t index = 0u; index < sizeof(input); ++index) input[index] = (uint8_t)index;
  for (unsigned port = 0u; port < CH348_PORT_COUNT; ++port) {
    assert(ch348_encode_transmit(output, sizeof(output), port, input,
                                 sizeof(input)) == sizeof(output));
    assert(output[0] == port && output[1] == 0xfdu && output[2] == 1u);
    assert(memcmp(output + 3u, input, sizeof(input)) == 0);
  }
  assert(ch348_encode_transmit(output, 2u, 0u, input, 1u) == 0u);
  assert(ch348_encode_transmit(output, 4u, 0u, input, 2u) == 0u);
  assert(ch348_encode_transmit(output, sizeof(output), 8u, input, 1u) == 0u);
}

static void test_receive(void) {
  uint8_t input[CH348_PORT_COUNT * CH348_RX_RECORD_SIZE] = {0};
  received_t received = {0};
  for (unsigned port = 0u; port < CH348_PORT_COUNT; ++port) {
    const size_t offset = port * CH348_RX_RECORD_SIZE;
    input[offset] = (uint8_t)port;
    input[offset + 1u] = CH348_RX_DATA_SIZE;
    for (size_t byte = 0u; byte < CH348_RX_DATA_SIZE; ++byte) {
      input[offset + 2u + byte] = (uint8_t)(port * 31u + byte);
    }
  }
  assert(ch348_decode_receive(input, sizeof(input), receive, &received) == 0);
  assert(received.calls == 8u);
  for (unsigned port = 0u; port < CH348_PORT_COUNT; ++port) {
    assert(received.sizes[port] == CH348_RX_DATA_SIZE);
    assert(memcmp(received.bytes[port], input + port * CH348_RX_RECORD_SIZE + 2u,
                  CH348_RX_DATA_SIZE) == 0);
  }
  received.calls = 0u;
  input[7u * CH348_RX_RECORD_SIZE + 1u] = 31u;
  assert(ch348_decode_receive(input, sizeof(input), receive, &received) != 0);
  assert(received.calls == 0u);
  input[7u * CH348_RX_RECORD_SIZE + 1u] = 30u;
  input[7u * CH348_RX_RECORD_SIZE] = 8u;
  assert(ch348_decode_receive(input, sizeof(input), receive, &received) != 0);
  assert(ch348_decode_receive(input, sizeof(input) - 1u, receive, &received) != 0);
}

static void test_status(void) {
  uint8_t input[12u + 8u * 3u] = {0u, 0xa1u};
  for (unsigned port = 0u; port < CH348_PORT_COUNT; ++port) {
    input[12u + port * 3u] = (uint8_t)port;
    input[12u + port * 3u + 1u] = 0x02u;
  }
  uint8_t mask = 0u;
  assert(ch348_decode_status(input, sizeof(input), &mask) == 0);
  assert(mask == 0xffu);
  assert(ch348_decode_status(input, sizeof(input) - 1u, &mask) != 0);
  assert(mask == 0u);
  input[12u] = 8u;
  assert(ch348_decode_status(input, sizeof(input), &mask) != 0);
  assert(mask == 0u);
}

int main(void) {
  test_configuration();
  test_transmit();
  test_receive();
  test_status();
  return 0;
}
