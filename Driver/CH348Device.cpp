#include "CH348Device.h"
#include "CH348Port.h"
#include "ch348_protocol.h"

#include <DriverKit/IOLib.h>
#include <DriverKit/IODispatchQueue.h>
#include <DriverKit/IOBufferMemoryDescriptor.h>
#include <DriverKit/OSArray.h>
#include <DriverKit/OSDictionary.h>
#include <DriverKit/OSNumber.h>
#include <USBDriverKit/IOUSBHostDevice.h>
#include <USBDriverKit/IOUSBHostInterface.h>
#include <USBDriverKit/USBDriverKitDefs.h>
#include <SerialDriverKit/SerialDriverKit.h>
#include <time.h>
#include <stdio.h>

struct CH348Device_IVars {
    IOUSBHostDevice *device;
    IOUSBHostInterface *interface;
    IOUSBHostPipe *pipes[4];
    IOBufferMemoryDescriptor *buffers[4];
    IOAddressSegment addresses[4];
    OSAction *actions[3];
    IOTimerDispatchSource *timer;
    OSAction *timeout_action;
    CH348Port *ports[8];
    bool active[8];
    uint32_t baud[8];
    uint32_t location;
    uint32_t max_transmit;
    uint32_t tx_port;
    uint32_t tx_size;
    uint32_t next_port;
    uint64_t tx_deadline;
    bool device_open;
    bool interface_open;
    bool stopping;
    bool small_package;
    bool tx_busy;
    bool tx_usb_done;
    bool tx_uart_done;
    bool tx_discard;
};

enum { DataIn, DataOut, StatusIn, ConfigOut };

bool CH348Device::init() {
    if (!super::init()) return false;
    ivars = IONewZero(CH348Device_IVars, 1);
    return ivars != nullptr;
}

void CH348Device::free() {
    Cleanup();
    IOSafeDeleteNULL(ivars, CH348Device_IVars, 1);
    super::free();
}

uint32_t CH348Device::Location() { return ivars->location; }
bool CH348Device::IsSmallPackage() { return ivars->small_package; }
bool CH348Device::IsStopping() { return ivars->stopping; }

kern_return_t IMPL(CH348Device, Start) {
    os_log(OS_LOG_DEFAULT, "CH348: starting USB device service");
    auto result = super::Start(provider, SUPERDISPATCH);
    if (result != kIOReturnSuccess) return result;
    ivars->device = OSDynamicCast(IOUSBHostDevice, provider);
    if (ivars->device == nullptr) return kIOReturnBadArgument;
    ivars->device->retain();
    result = ivars->device->Open(this, 0, 0);
    if (result != kIOReturnSuccess) { Cleanup(); return result; }
    ivars->device_open = true;
    os_log(OS_LOG_DEFAULT, "CH348: USB device opened");

    OSDictionary *properties = nullptr;
    result = ivars->device->CopyProperties(&properties);
    if (result != kIOReturnSuccess) { Cleanup(); return result; }
    auto vendor = OSDynamicCast(OSNumber, properties->getObject("idVendor"));
    auto product = OSDynamicCast(OSNumber, properties->getObject("idProduct"));
    auto location = OSDynamicCast(OSNumber, properties->getObject("locationID"));
    const bool matches = vendor && product && location &&
        vendor->unsigned32BitValue() == 0x1a86 && product->unsigned32BitValue() == 0x55d9;
    if (matches) ivars->location = location->unsigned32BitValue();
    properties->release();
    if (!matches) { Cleanup(); return kIOReturnUnsupported; }

    // Own the whole multiplexer. No separate driver may claim an individual UART.
    result = ivars->device->SetConfiguration(1, false);
    if (result != kIOReturnSuccess) { Cleanup(); return result; }
    uintptr_t iterator = 0;
    result = ivars->device->CreateInterfaceIterator(&iterator);
    if (result != kIOReturnSuccess) { Cleanup(); return result; }
    result = ivars->device->CopyInterface(iterator, &ivars->interface);
    (void)ivars->device->DestroyInterfaceIterator(iterator);
    if (result != kIOReturnSuccess || ivars->interface == nullptr) {
        Cleanup(); return kIOReturnNotFound;
    }
    result = ivars->interface->Open(this, 0, 0);
    if (result != kIOReturnSuccess) { Cleanup(); return result; }
    ivars->interface_open = true;
    const auto configuration = ivars->interface->CopyConfigurationDescriptor();
    const auto interface = configuration ? ivars->interface->GetInterfaceDescriptor(configuration) : nullptr;
    if (configuration == nullptr || interface == nullptr || interface->bNumEndpoints != 4 ||
        interface->bInterfaceNumber != 0 || interface->bAlternateSetting != 0) {
        if (configuration) IOFree(const_cast<IOUSBConfigurationDescriptor *>(configuration), configuration->wTotalLength);
        Cleanup(); return kIOReturnUnsupported;
    }
    unsigned inputs = 0, outputs = 0, endpoints = 0;
    const auto end = reinterpret_cast<const uint8_t *>(configuration) + configuration->wTotalLength;
    auto cursor = reinterpret_cast<const uint8_t *>(interface) + interface->bLength;
    result = kIOReturnSuccess;
    while (cursor + 2 <= end && endpoints < 4) {
        const uint8_t length = cursor[0];
        if (length < 2 || size_t(end - cursor) < length || cursor[1] == 4) {
            result = kIOReturnUnsupported; break;
        }
        if (cursor[1] == 5) {
            if (length < sizeof(IOUSBEndpointDescriptor)) { result = kIOReturnUnsupported; break; }
            const auto endpoint = reinterpret_cast<const IOUSBEndpointDescriptor *>(cursor);
            if ((endpoint->bmAttributes & 3) != 2 || endpoint->wMaxPacketSize < 32) {
                result = kIOReturnUnsupported; break;
            }
            unsigned slot;
            if ((endpoint->bEndpointAddress & 0x80) != 0) {
                if (inputs >= 2) { result = kIOReturnUnsupported; break; }
                slot = inputs++ == 0 ? DataIn : StatusIn;
            } else {
                if (outputs >= 2) { result = kIOReturnUnsupported; break; }
                slot = outputs++ == 0 ? DataOut : ConfigOut;
            }
            result = ivars->interface->CopyPipe(endpoint->bEndpointAddress, &ivars->pipes[slot]);
            if (result != kIOReturnSuccess) break;
            if (slot == DataOut) ivars->max_transmit = endpoint->wMaxPacketSize - 3;
            ++endpoints;
        }
        cursor += length;
    }
    IOFree(const_cast<IOUSBConfigurationDescriptor *>(configuration), configuration->wTotalLength);
    if (result != kIOReturnSuccess || endpoints != 4 || inputs != 2 || outputs != 2) {
        Cleanup(); return kIOReturnUnsupported;
    }
    if (ivars->max_transmit > 509) ivars->max_transmit = 509;
    os_log(OS_LOG_DEFAULT, "CH348: multiplexed interface and four bulk endpoints ready");
    for (unsigned slot = 0; slot < 4; ++slot) {
        result = ivars->device->CreateIOBuffer(kIOMemoryDirectionInOut, 512, &ivars->buffers[slot]);
        if (result == kIOReturnSuccess) result = ivars->buffers[slot]->SetLength(512);
        if (result == kIOReturnSuccess) result = ivars->buffers[slot]->GetAddressRange(&ivars->addresses[slot]);
        if (result != kIOReturnSuccess) { Cleanup(); return result; }
    }
    uint16_t version_size = 0;
    result = ivars->device->DeviceRequest(this, 0xc0, 0x96, 0, 0, 4,
        ivars->buffers[ConfigOut], &version_size, 1000);
    if (result != kIOReturnSuccess || version_size != 4) { Cleanup(); return kIOReturnIOError; }
    const auto version = reinterpret_cast<const uint8_t *>(ivars->addresses[ConfigOut].address);
    ivars->small_package = (version[1] & 0x80) != 0;
    os_log(OS_LOG_DEFAULT, "CH348: chip version 0x%x", version[0]);
    // Newer silicon supports independent upload on each UART. Enable the
    // vendor's packet upload mode before posting the shared receive transfer.
    uint8_t upload[CH348_UPLOAD_MODE_SIZE];
    const auto upload_size = ch348_encode_upload_mode(upload, version[0]);
    if (upload_size != 0) {
        result = Command(upload, uint32_t(upload_size));
        if (result != kIOReturnSuccess) { Cleanup(); return result; }
    }

    result = CreateActionReceiveComplete(0, &ivars->actions[0]);
    if (result == kIOReturnSuccess) result = CreateActionStatusComplete(0, &ivars->actions[1]);
    if (result == kIOReturnSuccess) result = CreateActionTransmitComplete(0, &ivars->actions[2]);
    IODispatchQueue *queue = nullptr;
    if (result == kIOReturnSuccess) result = CopyDispatchQueue(kIOServiceDefaultQueueName, &queue);
    if (result == kIOReturnSuccess) result = IOTimerDispatchSource::Create(queue, &ivars->timer);
    OSSafeReleaseNULL(queue);
    if (result == kIOReturnSuccess) result = CreateActionTransmitTimeout(0, &ivars->timeout_action);
    if (result == kIOReturnSuccess) result = ivars->timer->SetHandler(ivars->timeout_action);
    if (result == kIOReturnSuccess) result = ivars->timer->SetEnable(true);
    if (result != kIOReturnSuccess) { Cleanup(); return result; }

    for (unsigned index = 0; index < 8; ++index) {
        char key[32];
        snprintf(key, sizeof(key), "Port%uProperties", index);
        IOService *service = nullptr;
        result = Create(this, key, &service);
        os_log(OS_LOG_DEFAULT, "CH348: create UART%u returned 0x%x", index, result);
        auto port = OSDynamicCast(CH348Port, service);
        if (result != kIOReturnSuccess || port == nullptr) {
            OSSafeReleaseNULL(service); Cleanup(); return kIOReturnUnsupported;
        }
        ivars->ports[index] = port;
        if (!port->IsStarted()) result = port->Start(this);
        os_log(OS_LOG_DEFAULT, "CH348: start UART%u returned 0x%x", index, result);
        if (result != kIOReturnSuccess) { Cleanup(); return result; }
        ivars->baud[index] = 115200;
    }
    result = ivars->pipes[DataIn]->AsyncIO(ivars->buffers[DataIn], 512, ivars->actions[0], 0);
    if (result == kIOReturnSuccess)
        result = ivars->pipes[StatusIn]->AsyncIO(ivars->buffers[StatusIn], 512, ivars->actions[1], 0);
    if (result != kIOReturnSuccess) { Cleanup(); return result; }
    result = RegisterService();
    os_log(OS_LOG_DEFAULT, "CH348: eight UART services ready, registration 0x%x", result);
    return result;
}

kern_return_t IMPL(CH348Device, Stop) {
    Cleanup();
    return super::Stop(provider, SUPERDISPATCH);
}

void CH348Device::Cleanup() {
    if (ivars == nullptr) return;
    ivars->stopping = true;
    if (ivars->timer != nullptr) {
        // DriverKit invokes the cancellation handler asynchronously. It must
        // be non-null, and the timer's owned reference must survive until it
        // runs. The block deliberately does not capture this or ivars.
        IOTimerDispatchSource *timer = ivars->timer;
        ivars->timer = nullptr;
        const auto cancelled = timer->Cancel(^{ timer->release(); });
        if (cancelled != kIOReturnSuccess) timer->release();
    }
    for (auto &pipe : ivars->pipes) {
        if (pipe != nullptr) (void)pipe->Abort(kIOUSBAbortSynchronous, kIOReturnAborted, nullptr);
    }
    if (ivars->interface_open) { (void)ivars->interface->Close(this, 0); ivars->interface_open = false; }
    for (auto &port : ivars->ports) {
        if (port != nullptr) { (void)port->Terminate(0); OSSafeReleaseNULL(port); }
    }
    OSSafeReleaseNULL(ivars->timer);
    OSSafeReleaseNULL(ivars->timeout_action);
    for (auto &action : ivars->actions) OSSafeReleaseNULL(action);
    for (auto &buffer : ivars->buffers) OSSafeReleaseNULL(buffer);
    for (auto &pipe : ivars->pipes) OSSafeReleaseNULL(pipe);
    OSSafeReleaseNULL(ivars->interface);
    if (ivars->device_open) { (void)ivars->device->Close(this, 0); ivars->device_open = false; }
    OSSafeReleaseNULL(ivars->device);
}

void CH348Device::Fail(kern_return_t error) {
    if (ivars->stopping) return;
    os_log(OS_LOG_DEFAULT, "CH348: transport failure 0x%x", error);
    ivars->stopping = true;
    (void)Terminate(0);
}

kern_return_t CH348Device::Command(const uint8_t *data, uint32_t length) {
    if (ivars->stopping || ivars->pipes[ConfigOut] == nullptr) return kIOReturnNotReady;
    if (data == nullptr || length == 0 || length > 512) return kIOReturnBadArgument;
    memcpy(reinterpret_cast<void *>(ivars->addresses[ConfigOut].address), data, length);
    uint32_t written = 0;
    const auto result = ivars->pipes[ConfigOut]->IO(ivars->buffers[ConfigOut], length, &written, 1000);
    if (result != kIOReturnSuccess) return result;
    return written == length ? kIOReturnSuccess : kIOReturnUnderrun;
}

kern_return_t CH348Device::WriteRegister(uint32_t port, uint8_t reg,
                                        uint8_t value, bool bitWrite) {
    if (port >= 8) return kIOReturnBadArgument;
    if (reg == 2 && (value & 4) != 0 && ivars->tx_busy && ivars->tx_port == port)
        return kIOReturnBusy;
    const uint8_t command[] = {uint8_t(bitWrite ? 0x80 : 0xc0), ch348_register(port, reg), value};
    return Command(command, sizeof(command));
}

kern_return_t CH348Device::ConfigurePort(uint32_t port, uint32_t baud,
                                        uint8_t bits, uint8_t halfStops, uint8_t parity) {
    if (port >= 8 || (halfStops != 2 && halfStops != 4) ||
        parity < PD_RS232_PARITY_NONE || parity > PD_RS232_PARITY_EVEN) return kIOReturnUnsupported;
    if (ivars->tx_busy && ivars->tx_port == port) return kIOReturnBusy;
    uint8_t command[CH348_CONFIG_SIZE];
    if (ch348_encode_config(command, port, baud, bits, halfStops / 2, parity - 1) != 0)
        return kIOReturnBadArgument;
    const auto result = Command(command, sizeof(command));
    if (result == kIOReturnSuccess) ivars->baud[port] = baud;
    return result;
}

kern_return_t CH348Device::SetPortActive(uint32_t port, bool active) {
    if (port >= 8) return kIOReturnBadArgument;
    // Retire an old client's completion without advancing a newly opened ring.
    if (!active && ivars->tx_busy && ivars->tx_port == port) {
        ivars->tx_discard = true;
        ivars->active[port] = false;
        // Keep THRI enabled until the old write drains; otherwise its completion
        // would never arrive and closing one UART would stop all eight ports.
        return kIOReturnSuccess;
    }
    auto result = WriteRegister(port, 1, active ? 0x0f : 0, false);
    // Opening a new client initializes both UART FIFOs, as required by the
    // device's activation sequence. WriteRegister refuses to clear an active
    // in-flight transmit on this channel.
    if (active && result == kIOReturnSuccess) result = WriteRegister(port, 2, 0x87, false);
    // Enable only OUT2; do not rewrite DTR/RTS during activation or deactivation.
    if (active && result == kIOReturnSuccess) result = WriteRegister(port, 4, 0x31, true);
    // Start without hardware flow control, including when another OS or client
    // previously enabled it. This bit write also preserves DTR/RTS.
    if (active && result == kIOReturnSuccess) result = WriteRegister(port, 4, 0x50, true);
    if (result == kIOReturnSuccess) ivars->active[port] = active;
    return result;
}

int CH348Device::Deliver(uint32_t port, const uint8_t *data, uint32_t length) {
    if (port >= 8 || ivars->ports[port] == nullptr) return -1;
    return ivars->ports[port]->Receive(data, length);
}

static int deliver(void *context, unsigned port, const uint8_t *data, size_t length) {
    return static_cast<CH348Device *>(context)->Deliver(port, data, uint32_t(length));
}

void IMPL(CH348Device, ReceiveComplete) {
    (void)action; (void)completionTimestamp;
    if (ivars->stopping) return;
    if (status != kIOReturnSuccess || actualByteCount > 512) { Fail(status); return; }
    if (ch348_decode_receive(reinterpret_cast<const uint8_t *>(ivars->addresses[DataIn].address),
                             actualByteCount, deliver, this) != 0) { Fail(kIOReturnOverrun); return; }
    const auto result = ivars->pipes[DataIn]->AsyncIO(ivars->buffers[DataIn], 512, ivars->actions[0], 0);
    if (result != kIOReturnSuccess) Fail(result);
}

void IMPL(CH348Device, StatusComplete) {
    (void)action; (void)completionTimestamp;
    if (ivars->stopping) return;
    if (status != kIOReturnSuccess || actualByteCount > 512) { Fail(status); return; }
    const auto bytes = reinterpret_cast<const uint8_t *>(ivars->addresses[StatusIn].address);
    uint8_t empty = 0;
    if (ch348_decode_status(bytes, actualByteCount, &empty) != 0) { Fail(kIOReturnBadArgument); return; }
    for (uint32_t offset = 0; offset < actualByteCount;) {
        const uint8_t port = bytes[offset] & 0x0f;
        const uint8_t reg = bytes[offset + 1];
        if (reg == 0xa1) {
            const uint8_t target = bytes[offset + 2] & 0x0f;
            const uint32_t baud = (uint32_t(bytes[offset + 3]) << 24) |
                (uint32_t(bytes[offset + 4]) << 16) |
                (uint32_t(bytes[offset + 5]) << 8) | bytes[offset + 6];
            if (target < 8) ivars->ports[target]->ConfigurationAcknowledged(baud, port);
            offset += 12; continue;
        }
        if (reg >= 0x97 && reg <= 0x9d) { offset += 4; continue; }
        if (reg >= 0xa3 && reg <= 0xa7) { offset += reg == 0xa7 ? 10 : 3; continue; }
        if (reg != 0 && (reg & 0x0f) == 0) ivars->ports[port]->UpdateModem(bytes[offset + 2]);
        if ((reg & 0x0f) == 6) ivars->ports[port]->ReportLineError(bytes[offset + 2]);
        offset += 3;
    }
    if (ivars->tx_busy && (empty & (1u << ivars->tx_port)) != 0) {
        ivars->tx_uart_done = true;
        FinishTransmit();
    }
    const auto result = ivars->pipes[StatusIn]->AsyncIO(ivars->buffers[StatusIn], 512, ivars->actions[1], 0);
    if (result != kIOReturnSuccess) Fail(result);
}

void CH348Device::PumpTransmit() {
    if (ivars->stopping || ivars->tx_busy) return;
    auto buffer = reinterpret_cast<uint8_t *>(ivars->addresses[DataOut].address);
    for (unsigned offset = 0; offset < 8; ++offset) {
        const unsigned port = (ivars->next_port + offset) % 8;
        if (!ivars->active[port] || ivars->ports[port] == nullptr) continue;
        const uint32_t capacity = ivars->baud[port] < 9600 && ivars->max_transmit > 128
            ? 128 : ivars->max_transmit;
        uint8_t payload[509];
        const uint32_t size = ivars->ports[port]->CopyTransmit(payload, capacity);
        if (size == 0 || ivars->stopping) continue;
        const auto count = ch348_encode_transmit(buffer, 512, port, payload, size);
        if (count == 0) { Fail(kIOReturnBadArgument); return; }
        ivars->tx_busy = true; ivars->tx_usb_done = false; ivars->tx_uart_done = false;
        ivars->tx_discard = false;
        ivars->tx_port = port; ivars->tx_size = size; ivars->next_port = (port + 1) % 8;
        ivars->tx_deadline = clock_gettime_nsec_np(CLOCK_MONOTONIC_RAW) + 3000000000ull;
        auto result = ivars->timer->WakeAtTime(kIOTimerClockMonotonicRaw, ivars->tx_deadline, 0);
        if (result == kIOReturnSuccess)
            result = ivars->pipes[DataOut]->AsyncIO(ivars->buffers[DataOut], uint32_t(count), ivars->actions[2], 1000);
        if (result != kIOReturnSuccess) Fail(result);
        else ivars->ports[port]->RecordTransmitSubmission(size);
        return;
    }
}

void IMPL(CH348Device, TransmitComplete) {
    (void)action; (void)completionTimestamp;
    if (ivars->stopping) return;
    if (status != kIOReturnSuccess || actualByteCount != ivars->tx_size + 3) { Fail(kIOReturnIOError); return; }
    ivars->tx_usb_done = true;
    FinishTransmit();
}

void CH348Device::FinishTransmit() {
    if (!ivars->tx_busy || !ivars->tx_usb_done || !ivars->tx_uart_done || ivars->stopping) return;
    if (!ivars->tx_discard) ivars->ports[ivars->tx_port]->ConsumeTransmit(ivars->tx_size);
    if (!ivars->active[ivars->tx_port]) {
        const auto result = WriteRegister(ivars->tx_port, 1, 0, false);
        if (result != kIOReturnSuccess) { Fail(result); return; }
    }
    ivars->tx_busy = false;
    PumpTransmit();
}

void IMPL(CH348Device, TransmitTimeout) {
    (void)action; (void)time;
    if (ivars->tx_busy && clock_gettime_nsec_np(CLOCK_MONOTONIC_RAW) >= ivars->tx_deadline)
        Fail(kIOReturnTimeout);
}
