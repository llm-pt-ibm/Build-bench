#!/bin/bash
# Acceptance test of kismet: the server reports its version, and the USB Wi-Fi
# capture tool is built and its libraries resolve. It runs without network on
# what build.sh left in $BENCH_SRC_DIR ($BENCH_CACHE_DIR: scratch space) and
# passes with exit status 0.
set -euo pipefail
src=$BENCH_SRC_DIR/kismet
[ -x "$src/kismet" ] || { echo "error: the build left no kismet"; exit 1; }
"$src/kismet" --version
cap=$src/capture_userspace_usb_wifi/kismet_cap_usbwifi
[ -x "$cap" ] || { echo "error: the build left no kismet_cap_usbwifi"; exit 1; }
! ldd "$cap" | grep "not found"
echo "PASS kismet"
