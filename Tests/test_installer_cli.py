from pathlib import Path
import subprocess
import unittest


APP = Path(__file__).resolve().parents[1] / "build/Build/Products/Debug/CH348.app"


class InstallerCLITests(unittest.TestCase):
    @unittest.skipUnless(APP.is_dir(), "build the unsigned app before checking its CLI")
    def test_activation_failure_exits_without_a_desktop_event_loop(self):
        # This unsigned app is outside /Applications: activation must be rejected.
        process = subprocess.Popen([str(APP / "Contents/MacOS/CH348"), "--activate"],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            try:
                stdout, stderr = process.communicate(timeout=15)
            except subprocess.TimeoutExpired:
                self.fail("--activate waited for a GUI event loop instead of returning a failure")
            self.assertEqual(process.returncode, 1, stdout + stderr)
            self.assertIn("Activation failed:", stdout)
        finally:
            if process.poll() is None:
                process.terminate()
            process.communicate(timeout=5)
