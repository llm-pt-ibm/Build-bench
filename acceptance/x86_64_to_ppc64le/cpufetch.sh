#!/bin/bash
# Acceptance test of cpufetch: the built cpufetch runs on the build host and
# recognizes its CPU, a POWER processor.
set -uo pipefail
bin=$BENCH_SRC_DIR/cpufetch/cpufetch
[ -x "$bin" ] || { echo "error: the build left no cpufetch"; exit 1; }
"$bin" --version || { echo "error: cpufetch --version failed"; exit 1; }
out=$("$bin" 2>&1); rc=$?
echo "$out"
[ $rc -eq 0 ] || { echo "error: cpufetch exited with status $rc"; exit 1; }
grep -qi "power" <<< "$out" || { echo "error: cpufetch did not report a POWER processor"; exit 1; }
echo "PASS cpufetch"
