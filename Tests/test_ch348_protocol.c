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

static void test_transmit_in_place(void) {
  const size_t sizes[] = {1u, 128u, 509u};
  for (unsigned port = 0; port < CH348_PORT_COUNT; ++port) {
    for (size_t test = 0; test < sizeof(sizes) / sizeof(sizes[0]); ++test) {
      uint8_t guarded[514];
      uint8_t expected[509];
      memset(guarded, 0xa5, sizeof(guarded));
      uint8_t *out = guarded + 1;
      const size_t count = sizes[test];
      for (size_t i = 0; i < count; ++i) expected[i] = (uint8_t)(i + port);
      memcpy(out + 3, expected, count);
      assert(ch348_encode_transmit(out, 512, port, out + 3, count) == count + 3);
      assert(out[0] == port && out[1] == (uint8_t)count && out[2] == count >> 8);
      assert(memcmp(out + 3, expected, count) == 0);
      assert(guarded[0] == 0xa5 && guarded[513] == 0xa5);
      uint8_t before[514];
      memcpy(before, guarded, sizeof(before));
      assert(ch348_encode_transmit(out, count + 2, port, out + 3, count) == 0);
      assert(ch348_encode_transmit(out, 512, 8, out + 3, count) == 0);
      assert(ch348_encode_transmit(out, 512, port, out + 3, 0) == 0);
      assert(memcmp(before, guarded, sizeof(before)) == 0);
    }
  }
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
  assert(ch348_decode_status(input, sizeof(input), &mask, NULL, NULL) == 0);
  assert(mask == 0xffu);
  assert(ch348_decode_status(input, sizeof(input) - 1u, &mask, NULL, NULL) != 0);
  assert(mask == 0u);
  input[12u] = 8u;
  assert(ch348_decode_status(input, sizeof(input), &mask, NULL, NULL) != 0);
  assert(mask == 0u);
}

typedef struct status_capture {
  size_t calls;
  unsigned ports[16];
  uint8_t regs[16];
  size_t sizes[16];
} status_capture_t;

static void capture_status(void *user, unsigned port, uint8_t reg,
                            const uint8_t *record, size_t size) {
  status_capture_t *capture = user;
  assert(capture->calls < 16 && port < CH348_PORT_COUNT);
  assert(record[1] == reg);
  const size_t index = capture->calls++;
  capture->ports[index] = port;
  capture->regs[index] = reg;
  capture->sizes[index] = size;
}

static void test_status_records(void) {
  const uint8_t types[] = {0x00, 0x10, 0x02, 0x06, 0x85, 0x97, 0x9d, 0xa1, 0xa3, 0xa7};
  const size_t lengths[] = {3, 3, 3, 3, 4, 4, 4, 12, 3, 10};
  uint8_t input[64] = {0};
  size_t offsets[sizeof(types)], size = 0;
  for (size_t i = 0; i < sizeof(types); ++i) {
    offsets[i] = size;
    input[size] = (uint8_t)(i % CH348_PORT_COUNT);
    input[size + 1] = types[i];
    size += lengths[i];
  }
  status_capture_t capture = {0};
  uint8_t mask = 0;
  assert(ch348_decode_status(input, size, &mask, capture_status, &capture) == 0);
  assert(capture.calls == sizeof(types) && mask == (1u << 2));
  for (size_t i = 0; i < sizeof(types); ++i) {
    assert(capture.ports[i] == i % CH348_PORT_COUNT);
    assert(capture.regs[i] == types[i] && capture.sizes[i] == lengths[i]);
    for (size_t partial = 1; partial < lengths[i]; ++partial) {
      capture.calls = 0;
      mask = 0xff;
      assert(ch348_decode_status(input, offsets[i] + partial, &mask,
                                 capture_status, &capture) != 0);
      assert(capture.calls == 0 && mask == 0);
    }
  }
  input[offsets[sizeof(types) - 1]] = 8;
  capture.calls = 0;
  assert(ch348_decode_status(input, size, &mask, capture_status, &capture) != 0);
  assert(capture.calls == 0 && mask == 0);
}

static void test_modem_delta(void) {
  assert(ch348_merge_modem(0, 0x11) == 0x10);
  assert(ch348_merge_modem(0x10, 0x22) == 0x30);
  assert(ch348_merge_modem(0x30, 0x01) == 0x20);
  assert(ch348_merge_modem(0xf0, 0) == 0xf0);
  assert(ch348_merge_modem(0xf0, 0x0f) == 0);
  for (unsigned old = 0; old < 16; ++old) {
    for (unsigned status = 0; status < 256; ++status) {
      const uint8_t actual = ch348_merge_modem((uint8_t)(old << 4), (uint8_t)status);
      for (unsigned bit = 0; bit < 4; ++bit) {
        const unsigned expected = (status & (1u << bit))
            ? ((status >> (bit + 4)) & 1u) : ((old >> bit) & 1u);
        assert(((actual >> (bit + 4)) & 1u) == expected);
      }
    }
  }
}

int main(void) {
  test_configuration();
  test_transmit();
  test_transmit_in_place();
  test_receive();
  test_status();
  test_status_records();
  test_modem_delta();
  return 0;
}
