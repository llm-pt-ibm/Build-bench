#!/bin/bash
# Acceptance test of lite-xl-plugin-manager: the built lpm starts (its Lua
# code is built into it), reports its version, and its default architecture,
# with which it picks the binaries it downloads, is the build host's (a
# PowerPC, ppc64le, Linux one).
set -uo pipefail
bin=$BENCH_SRC_DIR/lite-xl-plugin-manager/build/lpm
[ -x "$bin" ] || { echo "error: the build left no build/lpm"; exit 1; }
work=$BENCH_CACHE_DIR/acceptance
rm -rf "$work" && mkdir -p "$work" && cd "$work"
export HOME=$work
version=$("$bin" --version 2>&1); rc=$?
echo "version: $version"
[ $rc -eq 0 ] && [ -n "$version" ] || { echo "error: lpm --version exited with status $rc"; exit 1; }
arch=$("$bin" --help 2>&1 | sed -n 's/.*Sets the architecture (default: \([^)]*\)).*/\1/p')
echo "default architecture: $arch"
[ -n "$arch" ] || { echo "error: lpm --help shows no default architecture"; exit 1; }
grep -qiE '(ppc|power).*linux' <<< "$arch" \
  || { echo "FAIL: the default architecture $arch is not the build host's (ppc64le Linux)"; exit 1; }
echo "PASS lpm"
