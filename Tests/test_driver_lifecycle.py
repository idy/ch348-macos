"""Exercise production queue teardown and TX retirement with memory-only stubs.

The extraction helper is shared with test_driver_receive. Teardown, deactivation,
cleanup, owner retirement, and TX consumption/completion are production bodies.
Only superclass calls, resources, statistics, register I/O, and scheduling are
stubbed. The fixture supplies an outstanding TX, queue replacement after
DisconnectQueues, and completion arrival; it does not establish IOUserSerial
callback ordering or model reopening a stopped child, DriverKit RPCs, or hardware.
"""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from test_driver_receive import ROOT, SANITIZERS, extract_definition


HOST_STUBS = r'''
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstring>

using kern_return_t = int;
constexpr int kIOReturnSuccess = 0, kIOReturnBadArgument = -1;
uint8_t ch348_register(unsigned, uint8_t) {
    assert(false && "Teardown must not request an activation-only modem query");
    return 0;
}
struct IOService {};
struct CH348Device;
struct Queue { uint32_t txPI = 0, txCI = 0; };
struct Resource {
    bool *owner_active = nullptr, *tx_discard = nullptr;
    unsigned *releases = nullptr, *active_releases = nullptr;
    unsigned *undiscarded_releases = nullptr;
    void release() {
        ++*releases;
        *active_releases += *owner_active;
        *undiscarded_releases += !*tx_discard;
    }
};
#define OSSafeReleaseNULL(value) do { \
    if ((value) != nullptr) { (value)->release(); (value) = nullptr; } \
} while (false)
#define SUPERDISPATCH 0
#define ARGS_Stop IOService *provider
#define ARGS_DisconnectQueues
#define ARGS_HwDeactivate
#define IMPL(type, method) type::method##_Impl(ARGS_##method)

struct CH348Port_IVars {
    CH348Device *owner = nullptr;
    uint32_t index = 3;
    bool active = true, started = true;
    Queue *queue = nullptr;
    Resource *tx_map = nullptr, *rx_map = nullptr, *interface_map = nullptr;
    Resource *tx_memory = nullptr, *rx_memory = nullptr, *interface_memory = nullptr;
    uint64_t tx_completed = 0;
};
struct SerialBase {
    unsigned disconnects = 0, stops = 0;
    int DisconnectQueues(int) { ++disconnects; return kIOReturnSuccess; }
    int Stop(IOService *provider, int) {
        assert(provider != nullptr);
        ++stops;
        return kIOReturnSuccess;
    }
};
struct CH348Port : SerialBase {
    using super = SerialBase;
    CH348Port_IVars *ivars = nullptr;
    unsigned snapshots = 0, notifications = 0;
    kern_return_t Stop_Impl(IOService *);
    kern_return_t DisconnectQueues_Impl();
    kern_return_t HwDeactivate_Impl();
    void Cleanup();
    void ConsumeTransmit(uint32_t);
    void PublishStatistics() { ++snapshots; }
    void TxFreeSpaceAvailable() { ++notifications; }
};
struct CH348Device_IVars {
    CH348Port *ports[8] = {};
    bool active[8] = {};
    bool stopping = false, tx_busy = true, tx_usb_done = false;
    bool tx_uart_done = false, tx_discard = false;
    uint32_t tx_port = 3, tx_size = 20;
};
struct CH348Device {
    CH348Device_IVars *ivars = nullptr;
    struct Write { uint32_t port; uint8_t reg, value; bool bit_write; } writes[16];
    unsigned write_count = 0, pumps = 0;
    int failure = 0;
    bool IsStopping();
    kern_return_t SetPortActive(uint32_t, bool);
    void FinishTransmit();
    int WriteRegister(uint32_t port, uint8_t reg, uint8_t value, bool bit_write) {
        assert(write_count < 16);
        writes[write_count++] = {port, reg, value, bit_write};
        return kIOReturnSuccess;
    }
    int Command(const uint8_t *, uint32_t) {
        assert(false && "Teardown must not send activation-only commands");
        return kIOReturnSuccess;
    }
    void PumpTransmit() { ++pumps; }
    void Fail(kern_return_t error) { failure = error; }
};
'''

HOST_FIXTURE = r'''
struct Fixture {
    CH348Device_IVars state;
    CH348Device device;
    CH348Port_IVars child;
    CH348Port port;
    IOService provider;
    Queue old_queue, replacement;
    Resource resources[6];
    unsigned releases = 0, active_releases = 0, undiscarded_releases = 0;

    Fixture() {
        device.ivars = &state;
        state.ports[3] = &port;
        state.active[3] = true;
        child.owner = &device;
        child.queue = &old_queue;
        port.ivars = &child;
        old_queue.txPI = 100;
        old_queue.txCI = 80;
        replacement.txPI = 7;
        for (auto &resource : resources) {
            resource.owner_active = &state.active[3];
            resource.tx_discard = &state.tx_discard;
            resource.releases = &releases;
            resource.active_releases = &active_releases;
            resource.undiscarded_releases = &undiscarded_releases;
        }
        child.tx_map = &resources[0];
        child.rx_map = &resources[1];
        child.interface_map = &resources[2];
        child.tx_memory = &resources[3];
        child.rx_memory = &resources[4];
        child.interface_memory = &resources[5];
    }
};

int main(int argc, char **argv) {
    assert(argc == 4);
    const bool stop = std::strcmp(argv[1], "stop") == 0;
    assert(stop || std::strcmp(argv[1], "disconnect") == 0);
    const auto scenario = argv[2];
    const bool usb_first = std::strcmp(argv[3], "usb-first") == 0;
    assert(usb_first || std::strcmp(argv[3], "uart-first") == 0);
    Fixture f;
    if (std::strcmp(scenario, "idle") == 0) f.state.tx_busy = false;
    else if (std::strcmp(scenario, "stopping") == 0) f.state.stopping = true;
    else if (std::strcmp(scenario, "repeated") == 0) {
        assert(f.port.HwDeactivate_Impl() == kIOReturnSuccess);
        assert(f.port.HwDeactivate_Impl() == kIOReturnSuccess);
    } else {
        assert(std::strcmp(scenario, "pending") == 0 ||
               std::strcmp(scenario, "unmapped") == 0);
    }
    const int result = stop ? f.port.Stop_Impl(&f.provider)
                            : f.port.DisconnectQueues_Impl();
    const bool detached = f.child.queue == nullptr && f.child.tx_map == nullptr &&
        f.child.rx_map == nullptr && f.child.interface_map == nullptr &&
        f.child.tx_memory == nullptr && f.child.rx_memory == nullptr &&
        f.child.interface_memory == nullptr;
    const bool retired = !f.state.active[3];
    const bool discard = f.state.tx_discard;
    const unsigned writes_before_completion = f.device.write_count;
    const unsigned teardown_snapshots = f.port.snapshots;
    // Queue installation is a host boundary: no stopped child is reopened.
    if (!stop && std::strcmp(scenario, "idle") != 0 &&
        std::strcmp(scenario, "unmapped") != 0)
        f.child.queue = &f.replacement;
    if (usb_first) f.state.tx_usb_done = true;
    else f.state.tx_uart_done = true;
    f.device.FinishTransmit();
    const uint32_t intermediate_consumer = f.replacement.txCI;
    const unsigned intermediate_writes = f.device.write_count;
    const unsigned intermediate_pumps = f.device.pumps;
    f.state.tx_usb_done = f.state.tx_uart_done = true;
    f.device.FinishTransmit();
    // A duplicate finish must not consume or schedule the completed TX twice.
    f.device.FinishTransmit();
    const bool busy_after_completion = f.state.tx_busy;
    const unsigned completion_writes = f.device.write_count;
    bool valid_writes = true;
    for (unsigned i = 0; i < f.device.write_count; ++i) {
        const auto &write = f.device.writes[i];
        valid_writes &= write.port == 3 && write.reg == 1 &&
            write.value == 0 && !write.bit_write;
    }
    std::printf("{\"result\":%d,\"retired\":%s,\"discard\":%s,"
                "\"detached\":%s,\"child_active\":%s,\"started\":%s,"
                "\"owner_present\":%s,\"releases\":%u,\"active_releases\":%u,"
                "\"undiscarded_releases\":%u,\"snapshots\":%u,"
                "\"writes_before_completion\":%u,\"intermediate_consumer\":%u,"
                "\"intermediate_writes\":%u,\"intermediate_pumps\":%u,"
                "\"replacement_consumer\":%u,\"replacement_producer\":%u,"
                "\"old_consumer\":%u,\"completed\":%llu,\"notifications\":%u,"
                "\"busy\":%s,\"writes\":%u,\"valid_writes\":%s,\"pumps\":%u,"
                "\"failure\":%d,\"super_disconnects\":%u,\"super_stops\":%u}\n",
                result, retired ? "true" : "false", discard ? "true" : "false",
                detached ? "true" : "false", f.child.active ? "true" : "false",
                f.child.started ? "true" : "false", f.child.owner ? "true" : "false",
                f.releases, f.active_releases, f.undiscarded_releases,
                teardown_snapshots, writes_before_completion, intermediate_consumer,
                intermediate_writes, intermediate_pumps, f.replacement.txCI,
                f.replacement.txPI, f.old_queue.txCI,
                static_cast<unsigned long long>(f.child.tx_completed),
                f.port.notifications, busy_after_completion ? "true" : "false",
                completion_writes, valid_writes ? "true" : "false", f.device.pumps,
                f.device.failure, f.port.disconnects, f.port.stops);
}
'''


@unittest.skipUnless(shutil.which("xcrun"), "Requires the Xcode host compiler")
class DriverLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        temporary = tempfile.TemporaryDirectory(prefix="ch348-host-lifecycle-")
        cls.addClassCleanup(temporary.cleanup)
        cls.binary = Path(temporary.name) / "lifecycle"
        definitions = [extract_definition(ROOT / "Driver/CH348Port.cpp", signature)
                       for signature in (
                           "kern_return_t IMPL(CH348Port, Stop)",
                           "kern_return_t IMPL(CH348Port, DisconnectQueues)",
                           "void CH348Port::Cleanup(",
                           "kern_return_t IMPL(CH348Port, HwDeactivate)",
                           "void CH348Port::ConsumeTransmit(")]
        definitions.extend(extract_definition(ROOT / "Driver/CH348Device.cpp", signature)
                           for signature in (
                               "bool CH348Device::IsStopping(",
                               "kern_return_t CH348Device::SetPortActive(",
                               "void CH348Device::FinishTransmit("))
        source = HOST_STUBS + "\n" + "\n".join(definitions) + "\n" + HOST_FIXTURE
        result = subprocess.run(
            ["xcrun", "clang++", "-std=c++17", "-Wall", "-Wextra", "-Werror",
             *SANITIZERS, "-x", "c++", "-", "-o", str(cls.binary)],
            input=source, text=True, capture_output=True, cwd=ROOT, timeout=60)
        if result.returncode:
            raise AssertionError(f"Host compilation failed:\n{result.stdout}{result.stderr}")

    def run_scenario(self, teardown, scenario="pending", order="usb-first"):
        result = subprocess.run([str(self.binary), teardown, scenario, order],
                                text=True, capture_output=True, cwd=ROOT, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def assert_teardown(self, result, teardown):
        self.assertEqual(result["result"], 0)
        self.assertTrue(result["detached"])
        self.assertFalse(result["child_active"])
        self.assertEqual(result["started"], teardown != "stop")
        self.assertEqual(result["owner_present"], teardown != "stop")
        self.assertEqual(result["releases"], 6)
        self.assertEqual(result["super_disconnects"], int(teardown == "disconnect"))
        self.assertEqual(result["super_stops"], int(teardown == "stop"))
        self.assertEqual(result["failure"], 0)
        self.assertTrue(result["valid_writes"])

    def assert_retired(self, result):
        self.assertTrue(result["retired"], "Teardown left owner port active")
        self.assertTrue(result["discard"], "Teardown did not retire the pending TX")
        self.assertEqual(result["active_releases"], 0,
                         "Mappings were released before owner deactivation")
        self.assertEqual(result["undiscarded_releases"], 0,
                         "Mappings were released before pending TX retirement")
        self.assertEqual(result["writes_before_completion"], 0,
                         "Pending TX must retain THRI until it drains")
        self.assertEqual(result["intermediate_writes"], 0)
        self.assertEqual(result["intermediate_pumps"], 0)
        self.assertEqual(result["intermediate_consumer"], 0)
        self.assertEqual(result["replacement_consumer"], 0,
                         "Old TX advanced the replacement ring")
        self.assertEqual(result["replacement_producer"], 7)
        self.assertEqual(result["old_consumer"], 80)
        self.assertEqual(result["completed"], 0)
        self.assertEqual(result["notifications"], 0)
        self.assertFalse(result["busy"])
        self.assertEqual(result["writes"], 1)
        self.assertEqual(result["pumps"], 1)

    def test_disconnect_without_deactivate_retires_tx_before_unmapping(self):
        result = self.run_scenario("disconnect")
        self.assert_retired(result)
        self.assert_teardown(result, "disconnect")

    def test_old_completion_does_not_advance_replacement_queue(self):
        for order in ("usb-first", "uart-first"):
            with self.subTest(order=order):
                result = self.run_scenario("disconnect", order=order)
                self.assertEqual(result["replacement_consumer"], 0,
                                 "Old TX consumed bytes from the replacement client")
                self.assert_retired(result)
                self.assert_teardown(result, "disconnect")

    def test_stop_without_deactivate_retires_tx_before_owner_is_cleared(self):
        for order in ("usb-first", "uart-first"):
            with self.subTest(order=order):
                result = self.run_scenario("stop", order=order)
                self.assert_retired(result)
                self.assert_teardown(result, "stop")

    def test_idle_teardown_deactivates_owner_without_a_discard(self):
        for teardown in ("disconnect", "stop"):
            with self.subTest(teardown=teardown):
                result = self.run_scenario(teardown, "idle")
                self.assertTrue(result["retired"])
                self.assertFalse(result["discard"])
                self.assertEqual(result["active_releases"], 0)
                self.assertEqual(result["writes_before_completion"], 1)
                self.assertEqual(result["writes"], 1)
                self.assertEqual(result["pumps"], 0)
                self.assertFalse(result["busy"])
                self.assertEqual(result["completed"], 0)
                self.assert_teardown(result, teardown)

    def test_stopping_owner_skips_register_io_and_completion(self):
        for teardown in ("disconnect", "stop"):
            with self.subTest(teardown=teardown):
                result = self.run_scenario(teardown, "stopping")
                self.assertEqual(result["writes"], 0)
                self.assertEqual(result["pumps"], 0)
                self.assertEqual(result["replacement_consumer"], 0)
                self.assertEqual(result["old_consumer"], 80)
                self.assertEqual(result["completed"], 0)
                self.assertEqual(result["notifications"], 0)
                self.assertTrue(result["busy"])
                self.assert_teardown(result, teardown)

    def test_repeated_deactivation_preserves_pending_tx_retirement(self):
        for teardown in ("disconnect", "stop"):
            with self.subTest(teardown=teardown):
                result = self.run_scenario(teardown, "repeated")
                self.assert_retired(result)
                self.assert_teardown(result, teardown)

    def test_completion_with_no_replacement_queue_is_safe(self):
        result = self.run_scenario("disconnect", "unmapped")
        self.assertEqual(result["old_consumer"], 80)
        self.assertEqual(result["completed"], 0)
        self.assertEqual(result["notifications"], 0)
        self.assertFalse(result["busy"])
        self.assertEqual(result["pumps"], 1)
        self.assert_teardown(result, "disconnect")


if __name__ == "__main__":
    unittest.main()
