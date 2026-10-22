#include "CH348Port.h"
#include "CH348Device.h"
#include "ch348_ring.h"

#include <DriverKit/IOLib.h>
#include <stdio.h>
#include <DriverKit/IODispatchQueue.h>
#include <DriverKit/IOBufferMemoryDescriptor.h>
#include <DriverKit/IOMemoryMap.h>
#include <DriverKit/OSDictionary.h>
#include <DriverKit/OSNumber.h>
#include <DriverKit/OSString.h>
#include <SerialDriverKit/SerialDriverKit.h>
#include <SerialDriverKit/SerialPortInterface.h>

struct CH348Port_IVars {
    CH348Device *owner;
    uint32_t index;
    uint32_t baud;
    uint8_t bits;
    uint8_t half_stops;
    uint8_t parity;
    uint8_t modem;
    bool started;
    bool active;
    IOBufferMemoryDescriptor *interface_memory;
    IOMemoryDescriptor *rx_memory;
    IOMemoryDescriptor *tx_memory;
    IOMemoryMap *interface_map;
    IOMemoryMap *rx_map;
    IOMemoryMap *tx_map;
    driverkit::serial::SerialPortInterface *queue;
    uint8_t *rx;
    uint8_t *tx;
    uint32_t rx_size;
    uint32_t tx_size;
    uint64_t tx_notifications;
    uint64_t tx_submitted;
    uint64_t tx_nonzero;
    uint64_t tx_completed;
    uint64_t rx_received;
    uint64_t rx_nonzero;
    uint64_t rx_delivered;
    uint64_t line_errors;
    uint8_t line_error_flags;
    uint64_t configuration_acks;
    uint32_t acknowledged_baud;
    uint32_t acknowledgement_source;
};

bool CH348Port::init() {
    if (!super::init()) return false;
    ivars = IONewZero(CH348Port_IVars, 1);
    if (ivars == nullptr) return false;
    ivars->baud = 115200;
    ivars->bits = 8;
    ivars->half_stops = 2;
    ivars->parity = PD_RS232_PARITY_NONE;
    return true;
}

void CH348Port::free() {
    Cleanup();
    IOSafeDeleteNULL(ivars, CH348Port_IVars, 1);
    super::free();
}

kern_return_t IMPL(CH348Port, Start) {
    os_log(OS_LOG_DEFAULT, "CH348: starting native serial child");
    kern_return_t result = super::Start(provider, SUPERDISPATCH);
    os_log(OS_LOG_DEFAULT, "CH348: serial superclass start 0x%x", result);
    if (result != kIOReturnSuccess) return result;
    ivars->owner = OSDynamicCast(CH348Device, provider);
    if (ivars->owner == nullptr) return kIOReturnBadArgument;
    OSDictionary *properties = nullptr;
    result = CopyProperties(&properties);
    if (result != kIOReturnSuccess) return result;
    auto index = OSDynamicCast(OSNumber, properties->getObject("PortIndex"));
    if (index == nullptr || index->unsigned32BitValue() >= 8) {
        properties->release();
        return kIOReturnBadArgument;
    }
    ivars->index = index->unsigned32BitValue();
    properties->release();

    IODispatchQueue *queue = nullptr;
    result = ivars->owner->CopyDispatchQueue(kIOServiceDefaultQueueName, &queue);
    if (result != kIOReturnSuccess) return result;
    result = SetDispatchQueue(kIOServiceDefaultQueueName, queue);
    queue->release();
    if (result != kIOReturnSuccess) return result;

    char suffix[40];
    snprintf(suffix, sizeof(suffix), "%08x-%u", ivars->owner->Location(), ivars->index);
    auto names = OSDictionary::withCapacity(2);
    auto name = OSString::withCString("CH348");
    auto ending = OSString::withCString(suffix);
    if (names == nullptr || name == nullptr || ending == nullptr) {
        OSSafeReleaseNULL(names); OSSafeReleaseNULL(name); OSSafeReleaseNULL(ending);
        return kIOReturnNoMemory;
    }
    names->setObject("IOTTYBaseName", name);
    names->setObject("IOTTYSuffix", ending);
    result = SetProperties(names);
    os_log(OS_LOG_DEFAULT, "CH348: UART%u serial naming 0x%x", ivars->index, result);
    names->release(); name->release(); ending->release();
    if (result != kIOReturnSuccess) return result;

    ivars->started = true;
    PublishStatistics();
    return RegisterService();
}

kern_return_t IMPL(CH348Port, Stop) {
    ivars->active = false;
    ivars->started = false;
    Cleanup();
    ivars->owner = nullptr;
    return super::Stop(provider, SUPERDISPATCH);
}

kern_return_t IMPL(CH348Port, ConnectQueues) {
    if (ivars->active) return kIOReturnBusy;
    Cleanup();
    // IOUserSerial calls this hook when a client opens the port. Map exactly
    // the buffers returned to that client, rather than allocating a separate
    // set in Start() which a subsequent open would replace.
    auto result = super::ConnectQueues(ifmd, rxqmd, txqmd, in_rxqmd, in_txqmd,
        in_rxqoffset, in_txqoffset, in_rxqlogsz, in_txqlogsz, SUPERDISPATCH);
    if (result != kIOReturnSuccess) return result;
    if (!*ifmd || !*rxqmd || !*txqmd) return kIOReturnNoMemory;
    ivars->interface_memory = *ifmd;
    ivars->rx_memory = *rxqmd;
    ivars->tx_memory = *txqmd;
    ivars->interface_memory->retain();
    ivars->rx_memory->retain();
    ivars->tx_memory->retain();
    result = ivars->interface_memory->CreateMapping(0, 0, 0, 0, 0, &ivars->interface_map);
    if (result == kIOReturnSuccess)
        result = ivars->rx_memory->CreateMapping(0, 0, 0, 0, 0, &ivars->rx_map);
    if (result == kIOReturnSuccess)
        result = ivars->tx_memory->CreateMapping(0, 0, 0, 0, 0, &ivars->tx_map);
    if (result != kIOReturnSuccess) { Cleanup(); return result; }
    if (ivars->interface_map->GetLength() < sizeof(*ivars->queue)) {
        Cleanup(); return kIOReturnBadArgument;
    }
    ivars->queue = reinterpret_cast<driverkit::serial::SerialPortInterface *>(
        ivars->interface_map->GetAddress());
    if (ivars->queue->rxqlogsz == 0 || ivars->queue->txqlogsz == 0 ||
        ivars->queue->rxqlogsz > 30 || ivars->queue->txqlogsz > 30) {
        Cleanup(); return kIOReturnBadArgument;
    }
    ivars->rx_size = 1u << ivars->queue->rxqlogsz;
    ivars->tx_size = 1u << ivars->queue->txqlogsz;
    if (uint64_t(ivars->queue->rxqoffset) + ivars->rx_size > ivars->rx_map->GetLength() ||
        uint64_t(ivars->queue->txqoffset) + ivars->tx_size > ivars->tx_map->GetLength()) {
        Cleanup(); return kIOReturnBadArgument;
    }
    ivars->rx = reinterpret_cast<uint8_t *>(ivars->rx_map->GetAddress()) + ivars->queue->rxqoffset;
    ivars->tx = reinterpret_cast<uint8_t *>(ivars->tx_map->GetAddress()) + ivars->queue->txqoffset;
    return kIOReturnSuccess;
}

kern_return_t IMPL(CH348Port, DisconnectQueues) {
    ivars->active = false;
    Cleanup();
    return super::DisconnectQueues(SUPERDISPATCH);
}

void CH348Port::Cleanup() {
    if (ivars == nullptr) return;
    ivars->queue = nullptr;
    OSSafeReleaseNULL(ivars->tx_map);
    OSSafeReleaseNULL(ivars->rx_map);
    OSSafeReleaseNULL(ivars->interface_map);
    OSSafeReleaseNULL(ivars->tx_memory);
    OSSafeReleaseNULL(ivars->rx_memory);
    OSSafeReleaseNULL(ivars->interface_memory);
}

bool CH348Port::IsStarted() { return ivars->started; }

kern_return_t IMPL(CH348Port, HwActivate) {
    if (ivars->owner == nullptr || ivars->owner->IsStopping() || ivars->queue == nullptr)
        return kIOReturnNotReady;
    kern_return_t result = ivars->owner->ConfigurePort(ivars->index, ivars->baud,
        ivars->bits, ivars->half_stops, ivars->parity);
    if (result == kIOReturnSuccess) result = ivars->owner->SetPortActive(ivars->index, true);
    if (result == kIOReturnSuccess) ivars->active = true;
    return result;
}

kern_return_t IMPL(CH348Port, HwDeactivate) {
    ivars->active = false;
    PublishStatistics();
    if (ivars->owner == nullptr || ivars->owner->IsStopping()) return kIOReturnSuccess;
    return ivars->owner->SetPortActive(ivars->index, false);
}

kern_return_t IMPL(CH348Port, HwProgramUART) {
    if (ivars->owner == nullptr) return kIOReturnNotReady;
    const auto result = ivars->owner->ConfigurePort(ivars->index, baudRate,
        nDataBits, nHalfStopBits, parity);
    if (result == kIOReturnSuccess) {
        ivars->baud = baudRate; ivars->bits = nDataBits;
        ivars->half_stops = nHalfStopBits; ivars->parity = parity;
    }
    return result;
}

kern_return_t IMPL(CH348Port, HwProgramBaudRate) {
    // Invoke the local hardware hook without sending another RPC.
    return HwProgramUART_Impl(baudRate, ivars->bits, ivars->half_stops, ivars->parity);
}

kern_return_t IMPL(CH348Port, HwResetFIFO) {
    if (ivars->owner == nullptr) return kIOReturnNotReady;
    return ivars->owner->WriteRegister(ivars->index, 2,
        0x81u | (tx ? 4u : 0u) | (rx ? 2u : 0u), false);
}

kern_return_t IMPL(CH348Port, HwSendBreak) {
    if (ivars->owner == nullptr) return kIOReturnNotReady;
    return ivars->owner->WriteRegister(ivars->index, 3, sendBreak ? 0x61 : 0x60, true);
}

kern_return_t IMPL(CH348Port, HwProgramMCR) {
    if (ivars->owner == nullptr) return kIOReturnNotReady;
    if (ivars->owner->IsSmallPackage() && ivars->index > 3) return kIOReturnUnsupported;
    auto result = ivars->owner->WriteRegister(ivars->index, 4, dtr ? 0x01 : 0x00, true);
    if (result == kIOReturnSuccess)
        result = ivars->owner->WriteRegister(ivars->index, 4, rts ? 0x11 : 0x10, true);
    return result;
}

kern_return_t IMPL(CH348Port, HwGetModemStatus) {
    if (!cts || !dsr || !ri || !dcd) return kIOReturnBadArgument;
    *cts = (ivars->modem & 0x10u) != 0;
    *dsr = (ivars->modem & 0x20u) != 0;
    *ri = (ivars->modem & 0x40u) != 0;
    *dcd = (ivars->modem & 0x80u) != 0;
    return kIOReturnSuccess;
}

kern_return_t IMPL(CH348Port, HwProgramLatencyTimer) {
    (void)latency;
    return kIOReturnUnsupported;
}

kern_return_t IMPL(CH348Port, HwProgramFlowControl) {
    (void)xon; (void)xoff;
    if (arg != 0) return kIOReturnUnsupported;
    if (ivars->owner == nullptr) return kIOReturnNotReady;
    return ivars->owner->WriteRegister(ivars->index, 4, 0x50, true);
}

void IMPL(CH348Port, TxDataAvailable) {
    ++ivars->tx_notifications;
    if (ivars->owner != nullptr && ivars->active) ivars->owner->PumpTransmit();
}

void IMPL(CH348Port, RxFreeSpaceAvailable) {}

uint32_t CH348Port::CopyTransmit(uint8_t *out, uint32_t capacity) {
    if (!ivars->active || ivars->queue == nullptr) return 0;
    const uint32_t producer = __atomic_load_n(&ivars->queue->txPI, __ATOMIC_ACQUIRE);
    const uint32_t consumer = __atomic_load_n(&ivars->queue->txCI, __ATOMIC_RELAXED);
    uint32_t count = 0;
    if (ch348_ring_peek(ivars->tx, ivars->tx_size, producer, consumer,
                         out, capacity, &count) != 0) {
        ivars->owner->Fail(kIOReturnBadArgument); return 0;
    }
    for (uint32_t index = 0; index < count; ++index)
        ivars->tx_nonzero += out[index] != 0;
    return count;
}

void CH348Port::RecordTransmitSubmission(uint32_t size) {
    ivars->tx_submitted += size;
}

void CH348Port::ConsumeTransmit(uint32_t size) {
    if (ivars->queue == nullptr) return;
    const uint32_t consumer = __atomic_load_n(&ivars->queue->txCI, __ATOMIC_RELAXED);
    __atomic_store_n(&ivars->queue->txCI, consumer + size, __ATOMIC_RELEASE);
    ivars->tx_completed += size;
    TxFreeSpaceAvailable();
}

int CH348Port::Receive(const uint8_t *data, uint32_t size) {
    ivars->rx_received += size;
    for (uint32_t index = 0; index < size; ++index)
        ivars->rx_nonzero += data[index] != 0;
    if (!ivars->active || ivars->queue == nullptr) return 0;
    const uint32_t producer = __atomic_load_n(&ivars->queue->rxPI, __ATOMIC_RELAXED);
    const uint32_t consumer = __atomic_load_n(&ivars->queue->rxCI, __ATOMIC_ACQUIRE);
    uint32_t next = producer;
    if (ch348_ring_append(ivars->rx, ivars->rx_size, producer, consumer,
                           data, size, &next) != 0) {
        RxError(true, false, false, false); return -1;
    }
    __atomic_store_n(&ivars->queue->rxPI, next, __ATOMIC_RELEASE);
    ivars->rx_delivered += size;
    RxDataAvailable();
    return 0;
}

void CH348Port::UpdateModem(uint8_t status) {
    ivars->modem = status;
    (void)SetModemStatus((status & 0x10) != 0, (status & 0x20) != 0,
                        (status & 0x40) != 0, (status & 0x80) != 0);
}

void CH348Port::ReportLineError(uint8_t status) {
    ++ivars->line_errors;
    ivars->line_error_flags |= status & 0x1e;
    (void)RxError((status & 2) != 0, (status & 16) != 0,
                  (status & 8) != 0, (status & 4) != 0);
}

void CH348Port::ConfigurationAcknowledged(uint32_t baud, uint32_t source) {
    ++ivars->configuration_acks;
    ivars->acknowledged_baud = baud;
    ivars->acknowledgement_source = source;
}

void CH348Port::PublishStatistics() {
    auto values = OSDictionary::withCapacity(17);
    if (values == nullptr) return;
    const struct { const char *name; uint64_t value; } counters[] = {
        {"CH348TxNotifications", ivars->tx_notifications},
        {"CH348TxSubmittedBytes", ivars->tx_submitted},
        {"CH348TxNonzeroBytes", ivars->tx_nonzero},
        {"CH348TxCompletedBytes", ivars->tx_completed},
        {"CH348RxReceivedBytes", ivars->rx_received},
        {"CH348RxNonzeroBytes", ivars->rx_nonzero},
        {"CH348RxDeliveredBytes", ivars->rx_delivered},
        {"CH348LineErrorEvents", ivars->line_errors},
        {"CH348LineErrorFlags", ivars->line_error_flags},
        {"CH348BaudRate", ivars->baud},
        {"CH348DataBits", ivars->bits},
        {"CH348HalfStopBits", ivars->half_stops},
        {"CH348Parity", ivars->parity},
        {"CH348DriverBuild", CH348_BUILD_NUMBER},
        {"CH348ConfigurationAcknowledgements", ivars->configuration_acks},
        {"CH348AcknowledgedBaudRate", ivars->acknowledged_baud},
        {"CH348AcknowledgementSource", ivars->acknowledgement_source},
    };
    for (const auto &counter : counters) {
        auto value = OSNumber::withNumber(counter.value, 64);
        if (value != nullptr) { values->setObject(counter.name, value); value->release(); }
    }
    // Snapshot at service start and client close, avoiding a registry RPC per packet.
    (void)SetProperties(values);
    values->release();
}
