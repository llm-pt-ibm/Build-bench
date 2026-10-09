#!/bin/bash
# Build a benchmark package in the local worker with `osc build`, resolving
# dependencies against openSUSE:Factory:PowerPC/standard (ppc64le), like OBS.
# Usage: scripts/local_worker/build.sh <package_dir> [jobs]
#        scripts/local_worker/build.sh --staged <package> [jobs]
#   --staged  build the sources already copied to <worker>/rootfs/var/tmp/bench-src/<package>
#   jobs      parallel jobs; 0 or omitted: one per 5 GB of available memory, at most nproc
# The build log is printed; the exit status is that of the build.
set -euo pipefail
W=${OBS_WORKER_ROOT:-/root/obs-worker}
R=$W/rootfs
PROJECT=${LOCAL_BUILD_PROJECT:-openSUSE:Factory:PowerPC}
REPO=${LOCAL_BUILD_REPO:-standard}
ARCH=${LOCAL_BUILD_ARCH:-ppc64le}
here=$(dirname "$0")

if [ "${1:-}" = "--staged" ]; then
  pkg=${2:?package}
  jobs=${3:-0}
  src=$R/var/tmp/bench-src/$pkg
  [ -d "$src" ] || { echo "no staged sources in $src" >&2; exit 2; }
else
  pkg_dir=${1:?package_dir}
  jobs=${2:-0}
  pkg=$(basename "$pkg_dir")
  # copy only the package sources (the same files that would be uploaded to OBS)
  src=$R/var/tmp/bench-src/$pkg
  rm -rf "$src" && mkdir -p "$src"
  for f in "$pkg_dir"/*; do
    case $(basename "$f") in
      log_failed.txt|log_failed_original.txt|manifest.json) continue ;;
    esac
    [ -f "$f" ] && cp -p "$f" "$src/"
  done
fi

if [ "$jobs" -le 0 ]; then
  mem_gb=$(awk '/MemAvailable/ {print int($2 / 1048576)}' /proc/meminfo)
  jobs=$(( mem_gb / 5 ))
  [ "$jobs" -gt "$(nproc)" ] && jobs=$(nproc)
  [ "$jobs" -lt 1 ] && jobs=1
fi

spec=$(cd "$src" && ls *.spec | head -1)
flavor=""
if [ -f "$src/_multibuild" ]; then
  flavor=$(grep -oE '<(package|flavor)>[^<]+' "$src/_multibuild" | head -1 | sed 's/.*>//')
fi
echo "local build: $pkg ($spec${flavor:+, flavor $flavor}) against $PROJECT/$REPO/$ARCH, $jobs jobs"
exec "$here/enter.sh" sh -c "cd /var/tmp/bench-src/$pkg && exec osc build --local-package \
  --alternative-project=$PROJECT --noservice --no-verify --trust-all-projects --clean \
  --vm-type=chroot --root=/var/tmp/build-root/$pkg -j $jobs ${flavor:+-M $flavor} \
  $REPO $ARCH $spec"
