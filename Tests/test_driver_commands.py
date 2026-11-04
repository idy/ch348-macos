"""Exercise the exact production Command definition with bounded host stubs.

The pipe scripts an initial result followed by success, making a blind replay
observable. Calls and copied bytes are recorded without emulating USB recovery.
This checks Command's policy, not DriverKit ABI/RPC, queue serialization, actual
endpoint recovery, or asynchronous termination. Fail is an observing stub; the
production Command body is extracted verbatim by the shared receive-test helper.
"""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from test_driver_receive import ROOT, SANITIZERS, extract_definition


SUCCESS = 0
NOT_READY = -1
BAD_ARGUMENT = -2
PIPE_STALLED = -3
IO_ERROR = -4
OVERRUN = -5
UNDERRUN = -6
TIMEOUT = -7
ABORTED = -8
NO_DEVICE = -9
RECOVERABLE = (PIPE_STALLED, IO_ERROR, OVERRUN, UNDERRUN)


HOST_STUBS = r'''
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>

using kern_return_t = int;
enum : kern_return_t {
    kIOReturnSuccess = 0, kIOReturnNotReady = -1, kIOReturnBadArgument = -2,
    kUSBHostReturnPipeStalled = -3, kIOReturnIOError = -4,
    kIOReturnOverrun = -5, kIOReturnUnderrun = -6, kIOReturnTimeout = -7,
    kIOReturnAborted = -8, kIOReturnNoDevice = -9
};
[[maybe_unused]] constexpr auto OS_LOG_DEFAULT = nullptr;
void os_log(decltype(nullptr), const char *, ...) {}
enum { DataIn, DataOut, StatusIn, ConfigOut };

struct Trace {
    const char *events[8] = {};
    unsigned count = 0;
    void record(const char *event) {
        assert(count < 8);
        events[count++] = event;
    }
};
struct Buffer { uint8_t bytes[512]; };
struct Address { uintptr_t address = 0; };
struct Pipe {
    Trace *trace = nullptr;
    Buffer *expected_buffer = nullptr;
    kern_return_t io_result = kIOReturnSuccess;
    kern_return_t clear_result = kIOReturnSuccess;
    uint32_t actual = 0, requested = 0, timeout = 0;
    unsigned io_calls = 0, clear_calls = 0;
    bool with_request = false;
    uint8_t payload[512] = {};

    kern_return_t IO(Buffer *buffer, uint32_t length, uint32_t *written,
                     uint32_t completionTimeoutMs) {
        assert(io_calls < 2);
        assert(buffer == expected_buffer && written != nullptr && length <= 512);
        trace->record("io");
        ++io_calls;
        requested = length;
        timeout = completionTimeoutMs;
        std::memcpy(payload, buffer->bytes, length);
        // Any unrequested replay succeeds, exposing both the extra call and
        // accidental replacement of the original command error with success.
        *written = io_calls == 1 ? actual : length;
        return io_calls == 1 ? io_result : kIOReturnSuccess;
    }
    kern_return_t ClearStall(bool withRequest) {
        assert(clear_calls < 2);
        trace->record("clear");
        ++clear_calls;
        with_request = withRequest;
        return clear_result;
    }
};
struct CH348Device_IVars {
    Pipe *pipes[4] = {};
    Buffer *buffers[4] = {};
    Address addresses[4];
    bool stopping = false;
};
struct CH348Device {
    CH348Device_IVars *ivars = nullptr;
    Trace *trace = nullptr;
    unsigned fail_calls = 0;
    kern_return_t fail_error = kIOReturnSuccess;
    kern_return_t Command(const uint8_t *, uint32_t);
    void Fail(kern_return_t error) {
        assert(fail_calls < 2);
        trace->record("fail");
        ++fail_calls;
        fail_error = error;
        ivars->stopping = true;
    }
};
'''

HOST_MAIN = r'''
int main(int argc, char **argv) {
    assert(argc == 6);
    const auto scenario = argv[1];
    Trace trace;
    Buffer buffer;
    std::memset(buffer.bytes, 0xcc, sizeof(buffer.bytes));
    uint8_t payload[512];
    for (unsigned i = 0; i < sizeof(payload); ++i)
        payload[i] = uint8_t(i * 37u + 0x5au);
    Pipe pipe;
    pipe.trace = &trace;
    pipe.expected_buffer = &buffer;
    pipe.io_result = int(std::strtol(argv[2], nullptr, 10));
    pipe.clear_result = int(std::strtol(argv[3], nullptr, 10));
    const auto length = uint32_t(std::strtoul(argv[4], nullptr, 10));
    pipe.actual = uint32_t(std::strtoul(argv[5], nullptr, 10));
    assert(length <= 513 && pipe.actual <= length);
    CH348Device_IVars state;
    state.pipes[ConfigOut] = &pipe;
    state.buffers[ConfigOut] = &buffer;
    state.addresses[ConfigOut].address = reinterpret_cast<uintptr_t>(buffer.bytes);
    const uint8_t *data = payload;
    if (std::strcmp(scenario, "null") == 0) data = nullptr;
    else if (std::strcmp(scenario, "stopping") == 0) state.stopping = true;
    else if (std::strcmp(scenario, "missing-pipe") == 0) state.pipes[ConfigOut] = nullptr;
    else assert(std::strcmp(scenario, "transfer") == 0);
    CH348Device device;
    device.ivars = &state;
    device.trace = &trace;
    const auto result = device.Command(data, length);
    bool buffer_unchanged = true, tail_unchanged = true;
    for (unsigned i = 0; i < sizeof(buffer.bytes); ++i) {
        if (buffer.bytes[i] != 0xcc) {
            buffer_unchanged = false;
            if (i >= length) tail_unchanged = false;
        }
    }
    std::printf("{\"result\":%d,\"io_calls\":%u,\"clear_calls\":%u,"
                "\"with_request\":%s,\"fail_calls\":%u,\"fail_error\":%d,"
                "\"stopping\":%s,\"buffer_unchanged\":%s,\"tail_unchanged\":%s,"
                "\"requested\":%u,\"timeout\":%u,\"events\":[",
                result, pipe.io_calls, pipe.clear_calls,
                pipe.with_request ? "true" : "false", device.fail_calls, device.fail_error,
                state.stopping ? "true" : "false", buffer_unchanged ? "true" : "false",
                tail_unchanged ? "true" : "false", pipe.requested, pipe.timeout);
    for (unsigned i = 0; i < trace.count; ++i)
        std::printf("%s\"%s\"", i ? "," : "", trace.events[i]);
    std::printf("],\"payload\":[");
    for (uint32_t i = 0; i < pipe.requested; ++i)
        std::printf("%s%u", i ? "," : "", unsigned(pipe.payload[i]));
    std::puts("]}");
}
'''


@unittest.skipUnless(shutil.which("xcrun"), "Requires the Xcode host compiler")
class DriverCommandTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        temporary = tempfile.TemporaryDirectory(prefix="ch348-host-commands-")
        cls.addClassCleanup(temporary.cleanup)
        cls.binary = Path(temporary.name) / "commands"
        definition = extract_definition(ROOT / "Driver/CH348Device.cpp",
                                        "kern_return_t CH348Device::Command(")
        source = HOST_STUBS + "\n" + definition + "\n" + HOST_MAIN
        result = subprocess.run(
            ["xcrun", "clang++", "-std=c++17", "-Wall", "-Wextra", "-Werror",
             *SANITIZERS, "-x", "c++", "-", "-o", str(cls.binary)],
            input=source, text=True, capture_output=True, cwd=ROOT, timeout=60)
        if result.returncode:
            raise AssertionError(f"Host compilation failed:\n{result.stdout}{result.stderr}")

    def run_command(self, scenario="transfer", error=SUCCESS, clear_error=SUCCESS,
                    length=6, written=None):
        if written is None:
            written = length
        result = subprocess.run(
            [str(self.binary), scenario, str(error), str(clear_error),
             str(length), str(written)],
            text=True, capture_output=True, cwd=ROOT, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def assert_no_recovery(self, result, io_calls=1):
        self.assertEqual(result["io_calls"], io_calls, "Command replayed the USB write")
        self.assertEqual(result["clear_calls"], 0)
        self.assertEqual(result["fail_calls"], 0)
        self.assertEqual(result["events"], ["io"] * io_calls)

    def test_success_copies_payload_and_submits_once(self):
        for length in (1, 6, 512):
            with self.subTest(length=length):
                result = self.run_command(length=length)
                self.assertEqual(result["result"], SUCCESS)
                self.assert_no_recovery(result)
                self.assertFalse(result["stopping"])
                self.assertEqual(result["requested"], length)
                self.assertEqual(result["timeout"], 1000)
                self.assertEqual(result["payload"], [(i * 37 + 0x5a) & 0xff
                                                      for i in range(length)])
                self.assertTrue(result["tail_unchanged"])

    def test_invalid_payload_is_rejected_without_io(self):
        for scenario, length in (("null", 6), ("transfer", 0), ("transfer", 513)):
            with self.subTest(scenario=scenario, length=length):
                result = self.run_command(scenario, length=length)
                self.assertEqual(result["result"], BAD_ARGUMENT)
                self.assert_no_recovery(result, io_calls=0)
                self.assertTrue(result["buffer_unchanged"])
                self.assertFalse(result["stopping"])

    def test_stopping_or_missing_pipe_is_rejected_without_io(self):
        for scenario in ("stopping", "missing-pipe"):
            with self.subTest(scenario=scenario):
                result = self.run_command(scenario)
                self.assertEqual(result["result"], NOT_READY)
                self.assert_no_recovery(result, io_calls=0)
                self.assertTrue(result["buffer_unchanged"])
                self.assertEqual(result["stopping"], scenario == "stopping")

    def test_recoverable_errors_clear_once_without_replay(self):
        for error in RECOVERABLE:
            with self.subTest(error=error):
                result = self.run_command(error=error, written=3)
                self.assertEqual(result["result"], error)
                self.assertEqual(result["io_calls"], 1, "Command replayed the USB write")
                self.assertEqual(result["clear_calls"], 1)
                self.assertTrue(result["with_request"])
                self.assertEqual(result["fail_calls"], 0)
                self.assertFalse(result["stopping"])
                self.assertEqual(result["events"], ["io", "clear"])

    def test_failed_clear_fails_transport_with_clear_error(self):
        for error in RECOVERABLE:
            with self.subTest(error=error):
                result = self.run_command(error=error, clear_error=NO_DEVICE, written=0)
                self.assertEqual(result["result"], error, "Clear error masked the USB error")
                self.assertEqual(result["fail_calls"], 1)
                self.assertEqual(result["fail_error"], NO_DEVICE)
                self.assertTrue(result["stopping"])
                self.assertEqual(result["io_calls"], 1, "Command replayed the USB write")
                self.assertEqual(result["clear_calls"], 1)
                self.assertTrue(result["with_request"])
                self.assertEqual(result["events"], ["io", "clear", "fail"])

    def test_timeout_and_cancellation_do_not_clear_or_replay(self):
        for error in (TIMEOUT, ABORTED):
            for written in (0, 3, 6):
                with self.subTest(error=error, written=written):
                    result = self.run_command(error=error, clear_error=NO_DEVICE,
                                              written=written)
                    self.assertEqual(result["result"], error)
                    self.assert_no_recovery(result)
                    self.assertFalse(result["stopping"])

    def test_short_write_does_not_clear_or_replay(self):
        for written in (0, 5):
            with self.subTest(written=written):
                result = self.run_command(clear_error=NO_DEVICE, written=written)
                self.assertEqual(result["result"], UNDERRUN)
                self.assert_no_recovery(result)
                self.assertFalse(result["stopping"])


if __name__ == "__main__":
    unittest.main()
