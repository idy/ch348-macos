#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
mkdir -p build/tests
xcrun clang -std=c11 -Wall -Wextra -Werror -fsanitize=address,undefined \
    -IProtocol Protocol/ch348_protocol.c Tests/test_ch348_protocol.c \
    -o build/tests/protocol
xcrun clang -std=c11 -Wall -Wextra -Werror -fsanitize=address,undefined \
    -IProtocol Protocol/ch348_ring.c Tests/test_ch348_ring.c \
    -o build/tests/ring
build/tests/protocol
build/tests/ring
python3 -m unittest discover -s Tests -p 'test_*.py'
