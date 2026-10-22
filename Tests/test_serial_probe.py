"""Exercise the probe's byte comparison and timeout behavior through a real PTY."""
import importlib.util
import os
from pathlib import Path
import pty
import select
import threading
import tty
import unittest


spec = importlib.util.spec_from_file_location(
    "serial_probe", Path(__file__).parents[1] / "scripts" / "serial-probe.py")
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class LoopbackProbeTests(unittest.TestCase):
    def setUp(self):
        self.master, self.slave = pty.openpty()
        tty.setraw(self.master)
        tty.setraw(self.slave)
        os.set_blocking(self.master, False)
        os.set_blocking(self.slave, False)
        self.stop = threading.Event()
        self.thread = None

    def tearDown(self):
        self.stop.set()
        if self.thread is not None:
            self.thread.join(timeout=2)
            self.assertFalse(self.thread.is_alive())
        os.close(self.master)
        os.close(self.slave)

    def echo(self, corrupt=False, extra_at=None):
        def run():
            pending = bytearray()
            seen = 0
            sent_extra = False
            while not self.stop.is_set():
                readers, writers, _ = select.select(
                    [self.master], [self.master] if pending else [], [], 0.01)
                if readers:
                    data = bytearray(os.read(self.master, 193))
                    if corrupt and seen == 0:
                        data[0] ^= 1
                    seen += len(data)
                    pending.extend(data)
                    if extra_at is not None and seen >= extra_at and not sent_extra:
                        pending.extend(b"extra")
                        sent_extra = True
                if writers:
                    count = os.write(self.master, pending[:97])
                    del pending[:count]

        self.thread = threading.Thread(target=run)
        self.thread.start()

    def test_binary_payload_and_partial_io(self):
        self.echo()
        result = probe.loopback(self.slave, 65536, 5)
        self.assertEqual(result["transmitted_bytes"], 65536)
        self.assertEqual(result["received_bytes"], 65536)
        self.assertEqual(len(result["sha256"]), 64)

    def test_corruption_is_rejected(self):
        self.echo(corrupt=True)
        with self.assertRaisesRegex(ValueError, "data mismatch"):
            probe.loopback(self.slave, 256, 1)

    def test_extra_bytes_are_rejected(self):
        self.echo(extra_at=32)
        with self.assertRaisesRegex(ValueError, "unexpected bytes|data mismatch"):
            probe.loopback(self.slave, 32, 1)

    def test_silent_receiver_times_out(self):
        with self.assertRaisesRegex(TimeoutError, "received 0 of 32"):
            probe.loopback(self.slave, 32, 0.03)

    def test_passive_capture_preserves_binary_bytes(self):
        data = b"ESP-IDF test\r\n\x00\xff\x11\x13"
        self.assertEqual(os.write(self.master, data), len(data))
        self.assertEqual(probe.capture(self.slave, 0.03), data)

    def test_passive_capture_silent_port_is_empty(self):
        self.assertEqual(probe.capture(self.slave, 0.02), b"")


if __name__ == "__main__":
    unittest.main()
