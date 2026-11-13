#!/bin/bash
# Acceptance test of libvarlink: the project's tests (meson test), but for
# test-object, which switches to the de_DE.UTF-8 locale the container lacks. It
# runs without network on what build.sh left in $BENCH_SRC_DIR
# ($BENCH_CACHE_DIR: scratch space) and passes with exit status 0.
set -euo pipefail
src=$BENCH_SRC_DIR/libvarlink
export LC_CTYPE=C.UTF-8
tests=$(meson test -C "$src/build" --list 2>/dev/null | grep -v -e '^libvarlink:test-object$' -e '^test-object$')
meson test -C "$src/build" --print-errorlogs --num-processes "$BENCH_JOBS" $tests
