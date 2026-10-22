#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
app="${1:-build/Build/Products/Release/CH348.app}"
python3 scripts/check-signing.py "$app"
destination="$HOME/Applications/CH348.app"
mkdir -p "$HOME/Applications"
if [ -e "$destination" ]; then
    identifier=$(/usr/libexec/PlistBuddy -c 'Print CFBundleIdentifier' "$destination/Contents/Info.plist")
    if [ "$identifier" != com.idy.ch348-macos ]; then
        echo "Destination belongs to another application: $destination" >&2
        exit 1
    fi
fi
ditto "$app" "$destination"
open "$destination" --args --activate
