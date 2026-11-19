import plistlib
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]


class PackageIdentityTests(unittest.TestCase):
    def test_custom_team_bundle_identity_survives_packaging(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "main.c"
            source.write_text("int main(void) { return 0; }\n")
            binary = root / "binary"
            subprocess.run(["xcrun", "clang", "-arch", "arm64", "-arch", "x86_64",
                            str(source), "-o", str(binary)], check=True, capture_output=True)
            app = root / "CH348.app"
            driver = app / "Contents/Library/SystemExtensions/com.example.custom.ch348.driver.dext"
            for contents, identifier, executable, kind in [
                (app / "Contents", "com.example.custom.ch348", "MacOS/CH348", "APPL"),
                (driver, "com.example.custom.ch348.driver", "com.example.custom.ch348.driver", "DEXT"),
            ]:
                target = contents / executable
                target.parent.mkdir(parents=True)
                target.write_bytes(binary.read_bytes())
                target.chmod(0o755)
                (contents / "Info.plist").write_bytes(plistlib.dumps({
                    "CFBundleIdentifier": identifier,
                    "CFBundleExecutable": Path(executable).name,
                    "CFBundleName": "CH348",
                    "CFBundlePackageType": kind,
                    "CFBundleShortVersionString": "0.1.1",
                    "CFBundleVersion": "13",
                }))
            result = subprocess.run([
                sys.executable, str(ROOT / "scripts/package.py"), "--unsigned",
                "--app", str(app), "--output-dir", str(root / "output"),
            ], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            package, = (root / "output").glob("*.pkg")
            expanded = root / "expanded"
            subprocess.run(["pkgutil", "--expand-full", str(package), str(expanded)],
                           check=True, capture_output=True)
            self.assertEqual(ET.parse(expanded / "PackageInfo").getroot().get("identifier"),
                             "com.example.custom.ch348.pkg")
            restored = expanded / "Payload/Applications/CH348.app/Contents"
            self.assertEqual(plistlib.loads((restored / "Info.plist").read_bytes())["CFBundleIdentifier"],
                             "com.example.custom.ch348")
            self.assertTrue((restored / "Library/SystemExtensions/com.example.custom.ch348.driver.dext").is_dir())
