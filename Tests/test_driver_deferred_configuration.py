"""Exercise production configuration admission and TX retirement together."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from test_driver_receive import ROOT, SANITIZERS, extract_definition

STUBS = r'''
#include "ch348_protocol.h"
#include <cassert>
#include <cstdint>
#include <cstring>
#include <string>
#include <vector>
using kern_return_t=int;
constexpr int kIOReturnSuccess=0, kIOReturnUnsupported=-1,
    kIOReturnBusy=-2, kIOReturnBadArgument=-3, kIOReturnIOError=-4, kIOReturnNotReady=-5;
constexpr uint8_t PD_RS232_PARITY_NONE=1, PD_RS232_PARITY_EVEN=3;
struct Port {
    std::vector<std::string> *events;
    void ConsumeTransmit(uint32_t size) { assert(size==1); events->push_back("consume"); }
};
struct State {
    bool active[8]={}, configuration_pending[8]={};
    uint8_t pending_configuration[8][CH348_CONFIG_SIZE]={};
    bool tx_busy=true, tx_usb_done=false, tx_uart_done=false,
         tx_discard=false, stopping=false;
    uint32_t tx_port=3, tx_size=1;
    Port *ports[8]={};
};
struct CH348Device {
    State *ivars;
    std::vector<std::string> events;
    std::vector<std::vector<uint8_t>> commands;
    int command_result=kIOReturnSuccess;
    int ConfigurePort(uint32_t,uint32_t,uint8_t,uint8_t,uint8_t);
    int SetPortActive(uint32_t,bool);
    void FinishTransmit();
    int Command(const uint8_t *bytes,uint32_t size) {
        events.push_back("command"); commands.emplace_back(bytes,bytes+size);
        return command_result;
    }
    int WriteRegister(uint32_t,uint8_t,uint8_t,bool) {
        events.push_back("register"); return kIOReturnSuccess;
    }
    void PumpTransmit() { events.push_back("pump"); }
    void Fail(int error) { assert(error==kIOReturnIOError); events.push_back("fail"); ivars->stopping=true; }
};
struct Fixture {
    State state;
    CH348Device device{&state,{},{},kIOReturnSuccess};
    Port port{&device.events};
    Fixture() { state.active[3]=true; state.ports[3]=&port; }
    void finish() { state.tx_usb_done=state.tx_uart_done=true; device.FinishTransmit(); }
};
'''

CASES = r'''
int main(int argc,char **argv) {
    assert(argc==2); std::string scenario=argv[1]; Fixture f;
    auto configure=[&](uint32_t baud) { return f.device.ConfigurePort(3,baud,8,2,1); };
    assert(configure(38400)==kIOReturnSuccess);
    assert(f.state.configuration_pending[3] && f.device.commands.empty());
    assert(configure(921600)==kIOReturnSuccess);
    uint8_t expected[CH348_CONFIG_SIZE];
    assert(ch348_encode_config(expected,3,921600,8,1,0)==0);
    assert(!memcmp(expected,f.state.pending_configuration[3],sizeof(expected)));
    if (scenario=="drain") {
        for (bool usb_first : {false,true}) {
            f.state.tx_usb_done=usb_first; f.state.tx_uart_done=!usb_first;
            f.device.FinishTransmit(); assert(f.device.events.empty());
        }
        f.finish();
        assert((f.device.events==std::vector<std::string>{"command","consume","pump"}));
        assert(f.device.commands.size()==1 && f.device.commands[0]==std::vector<uint8_t>(expected,expected+sizeof(expected)));
        assert(!f.state.configuration_pending[3] && !f.state.tx_busy);
        f.device.FinishTransmit(); assert(f.device.commands.size()==1);
    } else if (scenario=="invalid") {
        assert(configure(0)==kIOReturnBadArgument);
        assert(f.device.ConfigurePort(3,9600,9,2,1)==kIOReturnBadArgument);
        assert(f.device.ConfigurePort(3,9600,8,3,1)==kIOReturnUnsupported);
        assert(f.device.ConfigurePort(3,9600,8,2,0)==kIOReturnUnsupported);
        assert(f.device.ConfigurePort(8,9600,8,2,1)==kIOReturnUnsupported);
        assert(!memcmp(expected,f.state.pending_configuration[3],sizeof(expected)));
        assert(f.device.commands.empty());
    } else if (scenario=="close") {
        assert(f.device.SetPortActive(3,false)==kIOReturnSuccess);
        assert(!f.state.configuration_pending[3] && f.state.tx_discard && !f.state.active[3]);
        assert(configure(2000000)==kIOReturnBusy);
        f.finish();
        assert((f.device.events==std::vector<std::string>{"register","pump"}));
        assert(f.device.commands.empty());
    } else if (scenario=="failure") {
        f.device.command_result=kIOReturnIOError;
        f.finish();
        assert(f.state.stopping);
        assert((f.device.events==std::vector<std::string>{"command","fail"}));
    } else if (scenario=="independent") {
        assert(f.device.ConfigurePort(4,2000000,8,2,1)==kIOReturnSuccess);
        assert(f.device.commands.size()==1 && !f.state.configuration_pending[4]);
        assert(f.state.configuration_pending[3]);
        f.finish(); assert(f.device.commands.size()==2);
    } else if (scenario=="stopping") {
        f.state.stopping=true;
        assert(configure(2000000)==kIOReturnNotReady);
        f.finish(); assert(f.device.events.empty());
    } else if (scenario=="idle") {
        f.state.tx_busy=false;
        assert(configure(2000000)==kIOReturnSuccess);
        assert(f.device.commands.size()==1 && !f.state.configuration_pending[3]);
    } else assert(false);
}
'''


@unittest.skipUnless(shutil.which("xcrun"), "Requires the Xcode host compiler")
class DeferredConfigurationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        temporary = tempfile.TemporaryDirectory(prefix="ch348-host-deferred-")
        cls.addClassCleanup(temporary.cleanup)
        directory = Path(temporary.name)
        cls.binary = directory / "configuration"
        flags = ["-Wall", "-Wextra", "-Werror", *SANITIZERS, "-I" + str(ROOT / "Protocol")]
        obj = directory / "protocol.o"
        subprocess.run(["xcrun", "clang", "-std=c11", *flags, "-c",
                        str(ROOT / "Protocol/ch348_protocol.c"), "-o", str(obj)], check=True, timeout=60)
        bodies = [extract_definition(ROOT / "Driver/CH348Device.cpp", signature)
                  for signature in ("kern_return_t CH348Device::ConfigurePort(",
                                    "kern_return_t CH348Device::SetPortActive(",
                                    "void CH348Device::FinishTransmit(")]
        result = subprocess.run(["xcrun", "clang++", "-std=c++17", *flags,
                                 "-x", "c++", "-", "-x", "none", str(obj), "-o", str(cls.binary)],
                                input=STUBS + "\n" + "\n".join(bodies) + "\n" + CASES,
                                text=True, capture_output=True, timeout=60)
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)

    def scenario(self, name):
        result = subprocess.run([str(self.binary), name], text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_only_latest_configuration_applies_after_both_completions(self): self.scenario("drain")
    def test_invalid_settings_do_not_replace_pending_configuration(self): self.scenario("invalid")
    def test_close_discards_pending_settings_and_rejects_retired_owner(self): self.scenario("close")
    def test_configuration_failure_stops_before_consumption_or_next_write(self): self.scenario("failure")
    def test_another_uart_can_configure_independently(self): self.scenario("independent")
    def test_idle_configuration_is_immediate(self): self.scenario("idle")
    def test_stopping_does_not_accept_or_apply_pending_configuration(self): self.scenario("stopping")
