#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
xcodegen generate
case "${1:-}" in
    --unsigned)
        exec xcodebuild -project CH348.xcodeproj -scheme CH348 \
            -configuration Debug -derivedDataPath build CODE_SIGNING_ALLOWED=NO build
        ;;
    ""|--development)
        ch348_driver_entitlements=Driver/Driver.entitlements
        if [ "${1:-}" = --development ]; then
            ch348_driver_entitlements=Driver/Development.entitlements
        fi
        # A generic DriverKit host can produce a valid profile that omits this
        # Mac. Provision the concrete DriverKit host before embedding the dext.
        xcodebuild -project CH348.xcodeproj -scheme CH348Driver \
            -configuration Release -derivedDataPath build \
            -destination 'platform=macOS,variant=DriverKit,name=My Mac' \
            -allowProvisioningUpdates -allowProvisioningDeviceRegistration \
            CH348_DRIVER_ENTITLEMENTS="$ch348_driver_entitlements" \
            DEVELOPMENT_TEAM="${CH348_DEVELOPMENT_TEAM:-SV4P7RNRDK}" build
        exec xcodebuild -project CH348.xcodeproj -scheme CH348 \
            -configuration Release -derivedDataPath build \
            -destination 'platform=macOS,name=My Mac' \
            -allowProvisioningUpdates -allowProvisioningDeviceRegistration \
            CH348_DRIVER_ENTITLEMENTS="$ch348_driver_entitlements" \
            DEVELOPMENT_TEAM="${CH348_DEVELOPMENT_TEAM:-SV4P7RNRDK}" build
        ;;
    *) echo "Usage: $0 [--unsigned|--development]" >&2; exit 2 ;;
esac
