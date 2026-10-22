import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location(
    "signing", Path(__file__).resolve().parents[1] / "scripts/check-signing.py")
signing = importlib.util.module_from_spec(spec)
spec.loader.exec_module(signing)


class USBProfileTests(unittest.TestCase):
    def test_amfi_usb_profile_matching_and_explicit_development_consent(self):
        wildcard = [{"idVendor": "*"}]
        restricted = [{"idVendor": 0x1A86, "idProduct": 0x55D9}]
        self.assertFalse(signing.usb_signature_matches(wildcard, restricted))
        self.assertFalse(signing.usb_signature_matches(wildcard, wildcard))
        self.assertTrue(signing.usb_signature_matches(wildcard, wildcard, True))
        self.assertTrue(signing.usb_signature_matches(restricted, restricted))
        self.assertFalse(signing.usb_signature_matches(restricted, wildcard, True))

    def test_profile_must_include_the_installation_device(self):
        self.assertTrue(signing.permits_device({"ProvisionedDevices": ["local-mac"]}, "local-mac"))
        self.assertFalse(signing.permits_device({"ProvisionedDevices": ["other-mac"]}, "local-mac"))
        self.assertFalse(signing.permits_device({}, "local-mac"))
        self.assertTrue(signing.permits_device({"ProvisionsAllDevices": True}, "local-mac"))

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
