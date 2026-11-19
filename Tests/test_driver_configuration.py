"""Compile the production UART hook: repeated settings must not reprogram TX."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from test_driver_receive import ROOT, SANITIZERS, extract_definition

SOURCE = r'''
#include <cassert>
#include <cstdint>
using kern_return_t = int;
constexpr int kIOReturnSuccess=0, kIOReturnNotReady=-1, kIOReturnBusy=-2;
struct Owner {
    bool busy=true, stopping=false;
    unsigned calls=0;
    bool IsStopping() { return stopping; }
    int ConfigurePort(uint32_t, uint32_t, uint8_t, uint8_t, uint8_t) {
        ++calls;
        return busy ? kIOReturnBusy : kIOReturnSuccess;
    }
};
struct State {
    Owner *owner;
    unsigned index=0, baud=921600;
    uint8_t bits=8, half_stops=2, parity=1;
    bool active=true;
};
struct CH348Port {
    State *ivars;
    int HwProgramUART(uint32_t, uint8_t, uint8_t, uint8_t);
};
#define IMPL(type, method) type::method(uint32_t baudRate, uint8_t nDataBits, \
    uint8_t nHalfStopBits, uint8_t parity)
'''
MAIN = r'''
int main() {
    Owner owner;
    State state{&owner};
    CH348Port port{&state};
    assert(port.HwProgramUART(921600,8,2,1)==kIOReturnSuccess);
    assert(owner.calls==0);
    assert(port.HwProgramUART(2000000,8,2,1)==kIOReturnBusy);
    assert(port.HwProgramUART(921600,7,2,1)==kIOReturnBusy);
    assert(port.HwProgramUART(921600,8,4,1)==kIOReturnBusy);
    assert(port.HwProgramUART(921600,8,2,2)==kIOReturnBusy);
    assert(owner.calls==4 && state.baud==921600 && state.bits==8);
    state.active=false;
    assert(port.HwProgramUART(921600,8,2,1)==kIOReturnBusy);
    assert(owner.calls==5);
    owner.busy=false;
    assert(port.HwProgramUART(2000000,7,4,2)==kIOReturnSuccess);
    assert(owner.calls==6 && state.baud==2000000 && state.bits==7);
    assert(state.half_stops==4 && state.parity==2);
    state.active=true; owner.stopping=true;
    assert(port.HwProgramUART(2000000,7,4,2)==kIOReturnNotReady);
    assert(owner.calls==6);
    state.owner=nullptr;
    assert(port.HwProgramUART(2000000,7,4,2)==kIOReturnNotReady);
}
'''

@unittest.skipUnless(shutil.which('xcrun'), 'Requires the Xcode host compiler')
class DriverConfigurationTests(unittest.TestCase):
    def test_same_active_configuration_is_idempotent_without_masking_changes(self):
        body=extract_definition(ROOT/'Driver/CH348Port.cpp',
                                'kern_return_t IMPL(CH348Port, HwProgramUART)')
        with tempfile.TemporaryDirectory(prefix='ch348-host-config-') as directory:
            binary=Path(directory)/'configuration'
            compiled=subprocess.run(['xcrun','clang++','-std=c++17','-Wall','-Wextra',
                '-Werror',*SANITIZERS,'-x','c++','-','-o',str(binary)],
                input=SOURCE+'\n'+body+'\n'+MAIN,text=True,capture_output=True,timeout=60)
            self.assertEqual(compiled.returncode,0,compiled.stdout+compiled.stderr)
            result=subprocess.run([str(binary)],text=True,capture_output=True,timeout=10)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
