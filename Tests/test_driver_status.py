"""Run extracted production status handlers against the real C protocol decoder.

Only DriverKit transport and port notification/ack/error boundaries are stubbed;
this host regression does not exercise DriverKit dispatch or USB hardware.
"""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from test_driver_receive import ROOT, SANITIZERS, extract_definition


HOST_STUBS = r'''
#include "ch348_protocol.h"
#include <cassert>
#include <cstdint>
#include <string>
#include <utility>
#include <vector>
using IOReturn = int;
constexpr int kIOReturnSuccess = 0, kIOReturnBadArgument = -1;
enum { StatusIn };
struct Pipe {
    unsigned rearms = 0;
    int AsyncIO(void *, uint32_t size, void *, int timeout) {
        assert(size == 512 && timeout == 0);
        ++rearms;
        return kIOReturnSuccess;
    }
};
struct Address { uintptr_t address = 0; };
struct CH348Port_IVars { uint8_t modem = 0; };
struct CH348Port {
    CH348Port_IVars *ivars = nullptr;
    unsigned notifications = 0, acks = 0, errors = 0;
    uint8_t pins = 0, line = 0;
    uint32_t baud = 0, source = 0;
    void UpdateModem(uint8_t);
    int SetModemStatus(bool cts, bool dsr, bool ri, bool dcd) {
        ++notifications;
        pins = (cts ? 0x10 : 0) | (dsr ? 0x20 : 0) |
               (ri ? 0x40 : 0) | (dcd ? 0x80 : 0);
        return kIOReturnSuccess;
    }
    void ConfigurationAcknowledged(uint32_t b, uint32_t s) { ++acks; baud = b; source = s; }
    void ReportLineError(uint8_t s) { ++errors; line = s; }
};
struct CH348Device_IVars {
    CH348Port *ports[CH348_PORT_COUNT] = {};
    Address addresses[1];
    Pipe *pipes[1] = {};
    void *buffers[1] = {}, *actions[2] = {};
    bool stopping = false, tx_busy = true, tx_uart_done = false;
    unsigned tx_port = 2;
};
struct CH348Device {
    CH348Device_IVars *ivars = nullptr;
    unsigned failures = 0, finished = 0;
    void HandleStatus(uint32_t, uint8_t, const uint8_t *);
    void StatusComplete(void *, IOReturn, uint32_t, uint64_t);
    void Fail(int) { ++failures; ivars->stopping = true; }
    void FinishTransmit() { assert(ivars->tx_uart_done); ++finished; }
};
#define IMPL(type, method) type::method(void *action, IOReturn status, \
    uint32_t actualByteCount, uint64_t completionTimestamp)
'''

HOST_CASES = r'''
struct Fixture {
    CH348Port_IVars port_state[CH348_PORT_COUNT];
    CH348Port ports[CH348_PORT_COUNT];
    Pipe pipe;
    CH348Device_IVars state;
    CH348Device device;
    Fixture() {
        for (unsigned p = 0; p < CH348_PORT_COUNT; ++p) {
            ports[p].ivars = &port_state[p]; state.ports[p] = &ports[p];
        }
        state.pipes[StatusIn] = &pipe; device.ivars = &state;
    }
    void send(const std::vector<uint8_t> &bytes) {
        state.addresses[StatusIn].address = reinterpret_cast<uintptr_t>(bytes.data());
        device.StatusComplete(nullptr, kIOReturnSuccess, bytes.size(), 0);
    }
    void modem(unsigned p, uint8_t expected, unsigned count) {
        assert(port_state[p].modem == expected && ports[p].pins == expected);
        assert(ports[p].notifications == count);
    }
    unsigned events() const {
        unsigned count = 0;
        for (const auto &p : ports) count += p.notifications + p.acks + p.errors;
        return count;
    }
};
std::vector<uint8_t> mixed() {
    return {0, 0, 0x11,
            5, 0xa1, 0xa3, 0, 7, 8, 0, 0, 0, 0, 0, 0,
            4, 0x97, 0, 0,
            6, 0xa7, 1, 2, 3, 4, 5, 6, 7, 8,
            2, 0xa6, 0xff,
            7, 0x85, 0x3e, 0x80,
            1, 6, 0x0c, 2, 2, 0,
            0, 0, 0x22};
}
int main(int argc, char **argv) {
    assert(argc == 2);
    const std::string scenario = argv[1];
    Fixture f;
    if (scenario == "delta") {
        f.send({0, 0, 0x11}); f.modem(0, 0x10, 1);
        f.send({0, 0, 0x22}); f.modem(0, 0x30, 2);
        assert(f.events() == 2 && f.pipe.rearms == 2 && !f.device.failures);
    } else if (scenario == "mask") {
        f.send({0, 0, 0xff}); f.modem(0, 0xf0, 1);
        unsigned count = 1;
        for (auto [status, expected] : std::vector<std::pair<uint8_t, uint8_t>>{
                 {0x01, 0xe0}, {0xf0, 0xe0}, {0xd2, 0xc0}, {0xb4, 0x80}, {0x78, 0}}) {
            f.send({0, 0, status}); f.modem(0, expected, ++count);
        }
        assert(f.events() == count && f.pipe.rearms == count && !f.device.failures);
    } else if (scenario == "snapshot") {
        const uint8_t addresses[] = {6, 0x16, 0x26, 0x36, 0x0e, 0x1e, 0x2e, 0x3e};
        for (uint8_t p = 0; p < CH348_PORT_COUNT; ++p) {
            f.send({p, 0, 0xff});
            f.send({p, 0x85, addresses[p], 0x20}); f.modem(p, 0x20, 2);
            f.send({p, 0x85, uint8_t(addresses[p] ^ 0x10), 0xff});
            f.modem(p, 0x20, 2);
            f.send({p, 0x85, addresses[p], 0x80}); f.modem(p, 0x80, 3);
        }
        assert(f.events() == 24 && f.pipe.rearms == 32 && !f.device.failures);
    } else if (scenario == "mixed") {
        f.send(mixed()); f.modem(0, 0x30, 2); f.modem(7, 0x80, 1);
        assert(f.ports[3].acks == 1 && f.ports[3].baud == 460800 && f.ports[3].source == 5);
        assert(f.ports[1].errors == 1 && f.ports[1].line == 0x0c);
        assert(f.events() == 5 && f.state.tx_uart_done && f.device.finished == 1);
        assert(f.pipe.rearms == 1 && !f.device.failures);
    } else {
        assert(scenario == "malformed");
        for (const auto &tail : std::vector<std::vector<uint8_t>>{
                 {8, 0, 0x11}, {0}, {0, 0}, {0, 0x85, 6}, {0, 0x97, 0},
                 {0, 0xa1, 3, 0, 7, 8, 0, 0, 0, 0, 0}, {0, 0xa7, 0, 0, 0, 0, 0, 0, 0}}) {
            auto bytes = mixed(); bytes.insert(bytes.end(), tail.begin(), tail.end());
            unsigned callbacks = 0; uint8_t empty = 0xff;
            const auto count = [](void *ctx, unsigned, uint8_t, const uint8_t *, size_t) {
                ++*static_cast<unsigned *>(ctx);
            };
            assert(ch348_decode_status(bytes.data(), bytes.size(), &empty, count, &callbacks) != 0);
            assert(callbacks == 0 && empty == 0);
            Fixture bad; bad.send(bytes);
            assert(bad.events() == 0 && bad.device.failures == 1 && bad.state.stopping);
            assert(!bad.state.tx_uart_done && !bad.device.finished && !bad.pipe.rearms);
            for (unsigned p = 0; p < CH348_PORT_COUNT; ++p) bad.modem(p, 0, 0);
        }
    }
}
'''


@unittest.skipUnless(shutil.which("xcrun"), "Requires the Xcode host compiler")
class DriverStatusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        temporary = tempfile.TemporaryDirectory(prefix="ch348-host-status-")
        cls.addClassCleanup(temporary.cleanup)
        directory = Path(temporary.name)
        cls.binary = directory / "status"
        definitions = [extract_definition(ROOT / "Driver/CH348Port.cpp",
                                          "void CH348Port::UpdateModem(")]
        definitions.extend(extract_definition(ROOT / "Driver/CH348Device.cpp", signature)
                           for signature in ("void CH348Device::HandleStatus(",
                                             "static void status_record(",
                                             "void IMPL(CH348Device, StatusComplete)"))
        flags = ["-Wall", "-Wextra", "-Werror", *SANITIZERS, "-I" + str(ROOT / "Protocol")]
        obj = directory / "protocol.o"
        cls.compile(["xcrun", "clang", "-std=c11", *flags, "-c",
                     str(ROOT / "Protocol/ch348_protocol.c"), "-o", str(obj)])
        cls.compile(["xcrun", "clang++", "-std=c++17", *flags, "-x", "c++", "-",
                     "-x", "none", str(obj), "-o", str(cls.binary)],
                    HOST_STUBS + "\n" + "\n".join(definitions) + "\n" + HOST_CASES)

    @staticmethod
    def compile(command, source=None):
        result = subprocess.run(command, input=source, text=True, capture_output=True,
                                cwd=ROOT, timeout=60)
        if result.returncode:
            raise AssertionError(f"Host compilation failed:\n{result.stdout}{result.stderr}")

    def run_scenario(self, scenario):
        result = subprocess.run([str(self.binary), scenario], text=True,
                                capture_output=True, cwd=ROOT, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_modem_notifications_preserve_unchanged_cts(self): self.run_scenario("delta")
    def test_delta_masks_clear_selected_and_ignore_unselected_bits(self): self.run_scenario("mask")
    def test_read_snapshots_require_matching_port_address(self): self.run_scenario("snapshot")
    def test_mixed_records_dispatch_without_losing_framing(self): self.run_scenario("mixed")
    def test_malformed_transfer_has_no_callbacks_or_side_effects(self): self.run_scenario("malformed")


if __name__ == "__main__":
    unittest.main()
