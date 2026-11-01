"""Verify per-adapter channel checks using synthetic IOKit fixtures."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import plistlib
import unittest
from unittest.mock import patch


spec = importlib.util.spec_from_file_location(
    "verify_ports", Path(__file__).resolve().parents[1] / "scripts/verify-ports.py")
verify = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verify)


def adapter_ports(location, channels=range(8)):
    return [f"/dev/cu.CH348{location}-{channel}" for channel in channels]


class VerifyPortsTests(unittest.TestCase):
    def run_verifier(self, ports, arguments=(), builds=None):
        services = [{"IOCalloutDevice": port} for port in ports]
        drivers = []
        for port in ports:
            driver = {"CH348TxSubmittedBytes": 42,
                      "IORegistryEntryChildren": [{"IOCalloutDevice": port}]}
            if builds is None or port in builds:
                driver["CH348DriverBuild"] = 11 if builds is None else builds[port]
            drivers.append(driver)
        output = io.StringIO()
        with patch.object(verify.sys, "argv", ["verify-ports.py", *arguments]), \
                patch.object(verify.subprocess, "check_output", side_effect=[
                    plistlib.dumps(services), plistlib.dumps(drivers)]), \
                contextlib.redirect_stdout(output):
            status = verify.main()
        return status, json.loads(output.getvalue())

    def test_complete_adapters_pass_independently(self):
        locations = ["00100000", "20131000", "20132000"]
        for count in (1, 2, 3):
            with self.subTest(adapters=count):
                ports = [port for location in locations[:count]
                         for port in adapter_ports(location)]
                status, result = self.run_verifier(ports)
                self.assertEqual(status, 0)
                self.assertEqual(result["count"], count * 8)
                self.assertEqual(result["devices"],
                                 {location: list(range(8)) for location in locations[:count]})
                self.assertEqual(result["errors"], [])

    def test_no_adapter_fails(self):
        status, result = self.run_verifier([])
        self.assertEqual(status, 1)
        self.assertIn("No native CH348", result["errors"][0])

    def test_eight_ports_split_across_incomplete_adapters_fail(self):
        ports = adapter_ports("00100000", range(4)) + adapter_ports("20131000", range(4, 8))
        status, result = self.run_verifier(ports)
        self.assertEqual(status, 1)
        self.assertEqual(result["count"], 8)
        self.assertEqual(len(result["errors"]), 2)
        self.assertIn("00100000 is missing channels: [4, 5, 6, 7]", result["errors"][0])
        self.assertIn("20131000 is missing channels: [0, 1, 2, 3]", result["errors"][1])

    def test_incomplete_second_adapter_fails(self):
        ports = adapter_ports("00100000") + adapter_ports("20131000", range(7))
        status, result = self.run_verifier(ports)
        self.assertEqual(status, 1)
        self.assertIn("20131000 is missing channels: [7]", result["errors"][0])

    def test_unexpected_names_fail_even_with_complete_adapter(self):
        for name in ("/dev/cu.CH34800100000-8", "/dev/cu.CH34800100000-00",
                     "/dev/cu.CH348invalid-0"):
            with self.subTest(name=name):
                status, result = self.run_verifier(adapter_ports("00100000") + [name])
                self.assertEqual(status, 1)
                self.assertEqual(result["errors"], [f"Unexpected CH348 port name: {name}"])

    def test_build_and_statistics_cover_both_adapters(self):
        ports = adapter_ports("00100000") + adapter_ports("20131000")
        status, result = self.run_verifier(ports, ["--expected-build", "11", "--statistics"])
        self.assertEqual(status, 0)
        self.assertEqual(result["expected_build"], 11)
        self.assertEqual(set(result["runtime_builds"]), set(ports))
        self.assertEqual(set(result["statistics"]), set(ports))
        self.assertEqual(result["statistics"][ports[-1]]["CH348TxSubmittedBytes"], 42)

    def test_wrong_or_missing_build_on_second_adapter_fails(self):
        ports = adapter_ports("00100000") + adapter_ports("20131000")
        for actual in (10, None):
            with self.subTest(build=actual):
                builds = dict.fromkeys(ports, 11)
                if actual is None:
                    del builds[ports[-1]]
                else:
                    builds[ports[-1]] = actual
                status, result = self.run_verifier(ports, ["--expected-build", "11"], builds)
                self.assertEqual(status, 1)
                self.assertEqual(len(result["errors"]), 1)
                self.assertIn(ports[-1], result["errors"][0])


if __name__ == "__main__":
    unittest.main()
