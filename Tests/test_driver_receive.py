"""Exercise production receive definitions with a memory-only host boundary.

The named C++ definitions are extracted verbatim, not rewritten as test policy.
The stubs cover only the fields and external calls used by those definitions;
this does not check DriverKit ABI/RPC dispatch, concurrent queue access, hardware,
or asynchronous termination/cleanup. Changes to those dependencies may require
updating the stubs. Extraction handles ordinary comments and quoted literals,
but is not a C++ parser (for example, it does not handle raw string literals).
"""
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SANITIZERS = ["-fsanitize=address,undefined", "-fno-sanitize-recover=all"]


def extract_definition(path, signature):
    source = path.read_text()
    if source.count(signature) != 1:
        raise AssertionError(f"Expected one definition of {signature!r} in {path}")
    start = source.index(signature)
    # Preserve offsets while ignoring braces in ordinary comments and literals.
    tokens = r'/\*.*?\*/|//[^\n]*|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\''
    searchable = re.sub(tokens, lambda match: " " * len(match[0]),
                        source, flags=re.DOTALL)
    opening = searchable.index("{", start)
    depth = 0
    for offset in range(opening, len(searchable)):
        depth += (searchable[offset] == "{") - (searchable[offset] == "}")
        if depth == 0:
            return source[start:offset + 1]
    raise AssertionError(f"Unclosed definition of {signature!r} in {path}")


HOST_STUBS = r'''
#include "ch348_ring.h"
#include "ch348_protocol.h"
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>

using IOReturn = int;
using kern_return_t = int;
constexpr int kIOReturnSuccess = 0, kIOReturnOverrun = -1;
constexpr auto OS_LOG_DEFAULT = nullptr;
void os_log(decltype(nullptr), const char *, ...) {}
enum { DataIn };

struct Queue { uint32_t rxPI = 0, rxCI = 0; };
struct Pipe {
    unsigned rearms = 0;
    int AsyncIO(void *, uint32_t size, void *, int timeout) {
        assert(size == 512 && timeout == 0);
        ++rearms;
        return kIOReturnSuccess;
    }
};
struct Address { uintptr_t address = 0; };
struct CH348Port_IVars {
    uint64_t rx_received = 0, rx_nonzero = 0, rx_delivered = 0;
    bool active = true;
    Queue *queue = nullptr;
    uint8_t *rx = nullptr;
    uint32_t rx_size = 64;
};
struct CH348Port {
    CH348Port_IVars *ivars = nullptr;
    unsigned errors = 0, notifications = 0;
    int Receive(const uint8_t *, uint32_t);
    int RxError(bool overrun, bool gotBreak, bool framing, bool parity) {
        assert(overrun && !gotBreak && !framing && !parity);
        ++errors;
        return kIOReturnSuccess;
    }
    void RxDataAvailable() { ++notifications; }
};
struct CH348Device_IVars {
    CH348Port *ports[CH348_PORT_COUNT] = {};
    Address addresses[1];
    Pipe *pipes[1] = {};
    void *buffers[1] = {}, *actions[1] = {};
    bool stopping = false;
};
struct CH348Device {
    CH348Device_IVars *ivars = nullptr;
    unsigned terminations = 0;
    int Deliver(uint32_t, const uint8_t *, uint32_t);
    void ReceiveComplete(void *, IOReturn, uint32_t, uint64_t);
    void Fail(kern_return_t);
    int Terminate(uint64_t options) {
        assert(options == 0);
        ++terminations;
        return kIOReturnSuccess;
    }
};
#define IMPL(type, method) type::method(void *action, IOReturn status, \
    uint32_t actualByteCount, uint64_t completionTimestamp)
'''

HOST_FIXTURE = r'''
struct Fixture {
    uint8_t rings[CH348_PORT_COUNT][64] = {};
    Queue queues[CH348_PORT_COUNT];
    CH348Port_IVars port_state[CH348_PORT_COUNT];
    CH348Port ports[CH348_PORT_COUNT];
    Pipe pipe;
    CH348Device_IVars state;
    CH348Device device;
    // Healthy prefix and suffix keep every overflowing UART mid-transfer.
    uint8_t packet[(CH348_PORT_COUNT + 2) * CH348_RX_RECORD_SIZE] = {};
    uint8_t before[64];
    unsigned blocked;

    void record(unsigned slot, unsigned port) {
        const unsigned offset = slot * CH348_RX_RECORD_SIZE;
        packet[offset] = port;
        packet[offset + 1] = 1;
        packet[offset + 2] = 0x40 + slot;
    }
    Fixture(unsigned port, bool wrapped, uint32_t used) : blocked(port) {
        for (unsigned p = 0; p < CH348_PORT_COUNT; ++p) {
            std::memset(rings[p], 0x80 + p, sizeof(rings[p]));
            port_state[p].queue = &queues[p];
            port_state[p].rx = rings[p];
            ports[p].ivars = &port_state[p];
            state.ports[p] = &ports[p];
            record(p + 1, p);
        }
        record(0, (blocked + CH348_PORT_COUNT - 1) % CH348_PORT_COUNT);
        record(CH348_PORT_COUNT + 1, (blocked + 1) % CH348_PORT_COUNT);
        queues[blocked].rxCI = wrapped ? UINT32_MAX - 20u : 0;
        queues[blocked].rxPI = queues[blocked].rxCI + used;
        std::memcpy(before, rings[blocked], sizeof(before));
        state.addresses[DataIn].address = reinterpret_cast<uintptr_t>(packet);
        state.pipes[DataIn] = &pipe;
        device.ivars = &state;
    }
    void complete(uint32_t length = sizeof(packet)) {
        device.ReceiveComplete(nullptr, kIOReturnSuccess, length, 0);
    }
    void print() {
        std::printf("{\"stopping\":%s,\"terminations\":%u,\"rearms\":%u,"
                    "\"ring_unchanged\":%s,\"ports\":[",
                    state.stopping ? "true" : "false", device.terminations,
                    pipe.rearms, std::memcmp(before, rings[blocked], sizeof(before)) == 0
                        ? "true" : "false");
        for (unsigned p = 0; p < CH348_PORT_COUNT; ++p) {
            uint8_t bytes[64];
            uint32_t count = 0;
            const int result = ch348_ring_peek(rings[p], sizeof(rings[p]),
                queues[p].rxPI, queues[p].rxCI, bytes, sizeof(bytes), &count);
            std::printf("%s{\"received\":%llu,\"delivered\":%llu,\"errors\":%u,"
                        "\"notifications\":%u,\"producer\":%u,\"consumer\":%u,"
                        "\"queue_valid\":%s,\"bytes\":[", p ? "," : "",
                        static_cast<unsigned long long>(port_state[p].rx_received),
                        static_cast<unsigned long long>(port_state[p].rx_delivered),
                        ports[p].errors, ports[p].notifications,
                        queues[p].rxPI, queues[p].rxCI, result == 0 ? "true" : "false");
            for (uint32_t i = 0; i < count; ++i)
                std::printf("%s%u", i ? "," : "", bytes[i]);
            std::printf("]}");
        }
        std::puts("]}");
    }
};

int main(int argc, char **argv) {
    assert(argc == 4);
    const unsigned port = std::strtoul(argv[2], nullptr, 10);
    assert(port < CH348_PORT_COUNT);
    const bool wrapped = std::strcmp(argv[3], "1") == 0;
    const auto scenario = argv[1];
    uint32_t used = 63;
    if (std::strcmp(scenario, "insufficient") == 0 ||
        std::strcmp(scenario, "exact-fit") == 0) used = 62;
    if (std::strcmp(scenario, "invalid") == 0) used = 64;
    Fixture fixture(port, wrapped, used);
    uint32_t length = sizeof(fixture.packet);
    if (std::strcmp(scenario, "insufficient") == 0) {
        fixture.packet[(port + 1) * CH348_RX_RECORD_SIZE + 1] = 2;
        fixture.packet[(port + 1) * CH348_RX_RECORD_SIZE + 3] = 0x7f;
    } else if (std::strcmp(scenario, "malformed-length") == 0) {
        fixture.packet[length - CH348_RX_RECORD_SIZE + 1] = CH348_RX_DATA_SIZE + 1;
    } else if (std::strcmp(scenario, "malformed-port") == 0) {
        fixture.packet[length - CH348_RX_RECORD_SIZE] = CH348_PORT_COUNT;
    } else if (std::strcmp(scenario, "truncated") == 0) {
        --length;
    } else {
        assert(std::strcmp(scenario, "overflow") == 0 ||
               std::strcmp(scenario, "drain") == 0 ||
               std::strcmp(scenario, "exact-fit") == 0 ||
               std::strcmp(scenario, "invalid") == 0);
    }
    fixture.complete(length);
    if (std::strcmp(scenario, "drain") == 0) {
        fixture.queues[port].rxCI = fixture.queues[port].rxPI;
        fixture.packet[0] = port;
        fixture.packet[1] = 1;
        fixture.packet[2] = 0x5a;
        fixture.complete(CH348_RX_RECORD_SIZE);
    }
    fixture.print();
}
'''


@unittest.skipUnless(shutil.which("xcrun"), "Requires the Xcode host compiler")
class DriverReceiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        temporary = tempfile.TemporaryDirectory(prefix="ch348-host-receive-")
        cls.addClassCleanup(temporary.cleanup)
        directory = Path(temporary.name)
        cls.binary = directory / "receive"
        definitions = [extract_definition(ROOT / "Driver/CH348Port.cpp",
                                          "int CH348Port::Receive(")]
        definitions.extend(extract_definition(ROOT / "Driver/CH348Device.cpp", signature)
                           for signature in ("int CH348Device::Deliver(",
                                             "static int deliver(",
                                             "void IMPL(CH348Device, ReceiveComplete)",
                                             "void CH348Device::Fail("))
        flags = ["-Wall", "-Wextra", "-Werror", *SANITIZERS,
                 "-I" + str(ROOT / "Protocol")]
        objects = []
        # Keep the production C helpers in C mode; only driver definitions are C++.
        for name in ("ring", "protocol"):
            output = directory / f"{name}.o"
            cls.compile(["xcrun", "clang", "-std=c11", *flags, "-c",
                         str(ROOT / f"Protocol/ch348_{name}.c"), "-o", str(output)])
            objects.append(str(output))
        source = HOST_STUBS + "\n" + "\n".join(definitions) + "\n" + HOST_FIXTURE
        cls.compile(["xcrun", "clang++", "-std=c++17", *flags,
                     "-x", "c++", "-", "-x", "none", *objects,
                     "-o", str(cls.binary)], source)

    @staticmethod
    def compile(command, source=None):
        result = subprocess.run(command, input=source, text=True, capture_output=True,
                                cwd=ROOT, timeout=60)
        if result.returncode:
            raise AssertionError(f"Host compilation failed:\n{result.stdout}{result.stderr}")

    def run_scenario(self, scenario, port=3, wrapped=False):
        result = subprocess.run([str(self.binary), scenario, str(port), str(int(wrapped))],
                                text=True, capture_output=True, cwd=ROOT, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def assert_receiving(self, result, rearms=1):
        self.assertFalse(result["stopping"], "Port overflow stopped the shared USB device")
        self.assertEqual(result["terminations"], 0)
        self.assertEqual(result["rearms"], rearms)

    def assert_fatal(self, result):
        self.assertTrue(result["stopping"])
        self.assertEqual(result["terminations"], 1)
        self.assertEqual(result["rearms"], 0)

    def test_overflow_at_each_uart_preserves_later_records_and_rearms(self):
        for blocked in range(8):
            for wrapped in (False, True):
                with self.subTest(blocked=blocked, wrapped=wrapped):
                    result = self.run_scenario("overflow", blocked, wrapped)
                    self.assertTrue(result["ring_unchanged"])
                    self.assert_receiving(result)
                    records = [(blocked + 7) % 8, *range(8), (blocked + 1) % 8]
                    for port, state in enumerate(result["ports"]):
                        expected = [0x40 + slot for slot, target in enumerate(records)
                                    if target == port]
                        self.assertEqual(state["received"], len(expected))
                        self.assertEqual(state["errors"], int(port == blocked))
                        self.assertEqual(state["delivered"], 0 if port == blocked else len(expected))
                        self.assertEqual(state["notifications"], 0 if port == blocked else len(expected))
                        if port == blocked:
                            consumer = (2 ** 32 - 21) if wrapped else 0
                            self.assertEqual(state["consumer"], consumer)
                            self.assertEqual(state["producer"], (consumer + 63) % 2 ** 32)
                            self.assertEqual(state["bytes"], [0x80 + port] * 63)
                        else:
                            self.assertEqual(state["bytes"], expected)

    def test_overflowed_uart_resumes_after_client_drains(self):
        result = self.run_scenario("drain", wrapped=True)
        self.assert_receiving(result, rearms=2)
        state = result["ports"][3]
        self.assertEqual(state["received"], 2)
        self.assertEqual(state["delivered"], 1)
        self.assertEqual(state["notifications"], 1)
        self.assertEqual(state["errors"], 1)
        self.assertEqual(state["bytes"], [0x5a])

    def test_insufficient_space_drops_only_the_incoming_record(self):
        result = self.run_scenario("insufficient")
        self.assertTrue(result["ring_unchanged"])
        self.assert_receiving(result)
        state = result["ports"][3]
        self.assertEqual(state["producer"], 62)
        self.assertEqual(state["received"], 2)
        self.assertEqual(state["delivered"], 0)
        self.assertEqual(state["notifications"], 0)
        self.assertEqual(state["errors"], 1)
        self.assertEqual(result["ports"][4]["bytes"], [0x45, 0x49])

    def test_exact_fit_publishes_bytes_and_notifies(self):
        result = self.run_scenario("exact-fit")
        self.assert_receiving(result)
        state = result["ports"][3]
        self.assertEqual(state["producer"], 63)
        self.assertEqual(state["delivered"], 1)
        self.assertEqual(state["notifications"], 1)
        self.assertEqual(state["errors"], 0)
        self.assertEqual(state["bytes"], [0x83] * 62 + [0x44])

    def test_invalid_ring_state_remains_fatal(self):
        result = self.run_scenario("invalid")
        self.assert_fatal(result)
        self.assertTrue(result["ring_unchanged"])
        self.assertFalse(result["ports"][3]["queue_valid"])

    def test_malformed_transfer_is_fatal_before_any_delivery(self):
        for scenario in ("malformed-length", "malformed-port", "truncated"):
            with self.subTest(scenario=scenario):
                result = self.run_scenario(scenario)
                self.assert_fatal(result)
                for state in result["ports"]:
                    self.assertEqual(state["received"], 0)
                    self.assertEqual(state["delivered"], 0)
                    self.assertEqual(state["notifications"], 0)
                    self.assertEqual(state["errors"], 0)


if __name__ == "__main__":
    unittest.main()
