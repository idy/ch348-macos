import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location(
    "signing", Path(__file__).resolve().parents[1] / "scripts/check-signing.py")
signing = importlib.util.module_from_spec(spec)
spec.loader.exec_module(signing)


class USBProfileTests(unittest.TestCase):
    def test_development_profile_wildcard_does_not_broaden_driver_signature(self):
        profile = [{"idVendor": "*"}]
        self.assertTrue(signing.grants_ch348(profile, True))
        self.assertFalse(signing.grants_ch348(profile))

    def test_exact_and_vendor_scoped_grants(self):
        self.assertTrue(signing.grants_ch348([{"idVendor": 0x1A86, "idProduct": 0x55D9}]))
        self.assertTrue(signing.grants_ch348([{"idVendor": 0x1A86}]))

    def test_unrelated_devices_and_malformed_grants_are_rejected(self):
        for grant in [[{"idVendor": 0x1A86, "idProduct": 0x7523}],
                      [{"idVendor": 0x1234}], [{"idProduct": 0x55D9}],
                      ["*"], "*", None, []]:
            self.assertFalse(signing.grants_ch348(grant, True))
