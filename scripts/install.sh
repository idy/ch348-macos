#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
ch348_development=
if [ "${1:-}" = --development ]; then
    ch348_development=--development
    shift
fi
app="${1:-build/Build/Products/Release/CH348.app}"
if [ -n "$ch348_development" ]; then
    python3 scripts/check-signing.py --development "$app"
else
    python3 scripts/check-signing.py "$app"
fi
destination="/Applications/CH348.app"
if [ ! -w /Applications ]; then
    echo "Administrator access is required to copy CH348.app into /Applications." >&2
    echo "Copy the signed app there with Finder, then open it and choose Install / Update." >&2
    exit 1
fi
if [ -e "$destination" ]; then
    identifier=$(/usr/libexec/PlistBuddy -c 'Print CFBundleIdentifier' "$destination/Contents/Info.plist")
    if [ "$identifier" != com.idy.ch348-macos ]; then
        echo "Destination belongs to another application: $destination" >&2
        exit 1
    fi
fi
ditto "$app" "$destination"
open -n "$destination" --args --activate
