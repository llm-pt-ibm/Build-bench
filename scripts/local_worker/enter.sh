#!/bin/bash
# Run a command inside the local build worker (openSUSE Tumbleweed chroot).
# Usage: scripts/local_worker/enter.sh <command> [args...]
set -euo pipefail
R=${OBS_WORKER_ROOT:-/root/obs-worker}/rootfs
[ -x "$R/usr/bin/zypper" ] || { echo "worker not set up: run scripts/local_worker/setup.sh" >&2; exit 1; }
# the host's resolver (Docker's embedded DNS here) fails at times; public
# servers after it are tried when it does (WORKER_FALLBACK_DNS="" disables them)
{ grep -v "^options" /etc/resolv.conf
  for ns in ${WORKER_FALLBACK_DNS-1.1.1.1 8.8.8.8}; do echo "nameserver $ns"; done
  echo "options timeout:2 attempts:2"; } > "$R/etc/resolv.conf"
mountpoint -q "$R/proc" || mount -t proc proc "$R/proc"
mountpoint -q "$R/sys" || mount --rbind /sys "$R/sys"
mountpoint -q "$R/dev" || mount --rbind /dev "$R/dev"
exec chroot "$R" /usr/bin/env -i HOME=/root TERM="${TERM:-xterm}" LANG=C.UTF-8 \
  PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin "$@"
