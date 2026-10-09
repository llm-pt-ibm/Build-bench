#!/bin/bash
# Run a command inside the local build worker (openSUSE Tumbleweed chroot).
# Usage: scripts/local_worker/enter.sh <command> [args...]
set -euo pipefail
R=${OBS_WORKER_ROOT:-/root/obs-worker}/rootfs
[ -x "$R/usr/bin/zypper" ] || { echo "worker not set up: run scripts/local_worker/setup.sh" >&2; exit 1; }
cp /etc/resolv.conf "$R/etc/resolv.conf"
mountpoint -q "$R/proc" || mount -t proc proc "$R/proc"
mountpoint -q "$R/sys" || mount --rbind /sys "$R/sys"
mountpoint -q "$R/dev" || mount --rbind /dev "$R/dev"
exec chroot "$R" /usr/bin/env -i HOME=/root TERM="${TERM:-xterm}" LANG=C.UTF-8 \
  PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin "$@"
