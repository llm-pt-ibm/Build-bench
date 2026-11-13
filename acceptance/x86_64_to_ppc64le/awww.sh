#!/bin/bash
# Acceptance test of awww: the project's tests (cargo test), and its two
# programs run. It runs without network on what build.sh left in $BENCH_SRC_DIR
# ($BENCH_CACHE_DIR: scratch space) and passes with exit status 0.
set -euo pipefail
src=$BENCH_SRC_DIR/awww
bin=$src/target/release/awww
[ -x "$bin" ] || { echo "error: the build left no awww"; exit 1; }
"$bin" --version
bin=$src/target/release/awww-daemon
[ -x "$bin" ] || { echo "error: the build left no awww-daemon"; exit 1; }
"$bin" --version
cd "$src"
export CARGO_HOME=$BENCH_CACHE_DIR/cargo CARGO_NET_OFFLINE=true
cargo test --release --offline --jobs "$BENCH_JOBS"
