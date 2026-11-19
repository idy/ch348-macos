"""Keep installer, driver and package identities aligned for local signing."""
import plistlib
import re


def bundle_identity(app):
    identifier = plistlib.loads((app / "Contents/Info.plist").read_bytes()).get("CFBundleIdentifier")
    if not isinstance(identifier, str) or not re.fullmatch(r"[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+", identifier):
        raise ValueError("Invalid installer bundle identifier")
    return identifier, app / f"Contents/Library/SystemExtensions/{identifier}.driver.dext"
