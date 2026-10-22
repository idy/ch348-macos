#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
xcodegen generate
case "${1:-}" in
    --unsigned)
        exec xcodebuild -project CH348.xcodeproj -scheme CH348 \
            -configuration Debug -derivedDataPath build CODE_SIGNING_ALLOWED=NO build
        ;;
    "")
        exec xcodebuild -project CH348.xcodeproj -scheme CH348 \
            -configuration Release -derivedDataPath build \
            -allowProvisioningUpdates -allowProvisioningDeviceRegistration \
            DEVELOPMENT_TEAM="${CH348_DEVELOPMENT_TEAM:-SV4P7RNRDK}" build
        ;;
    *) echo "Usage: $0 [--unsigned]" >&2; exit 2 ;;
esac
