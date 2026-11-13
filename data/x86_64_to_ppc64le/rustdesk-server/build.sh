#!/bin/bash
# Build recipe for rustdesk-server, as it builds on x86_64: Cargo, with its git
# submodule libs/hbb_common (../hbb_common), with the crates vendored for it
# (../vendor), unpacked into the sources as the distribution does. It runs from
# the case directory in the environment envs/rust-power9, with $BENCH_CACHE_DIR
# (this run's build state), $BENCH_SHARED_CACHE_DIR (caches kept across runs)
# and $BENCH_JOBS.
set -euo pipefail
cd rustdesk-server
cp -a ../vendor/Cargo.lock .
cp -a ../vendor/.cargo .
[ -f libs/hbb_common/Cargo.toml ] || { rmdir libs/hbb_common 2>/dev/null || true; ln -sfn ../../hbb_common libs/hbb_common; }
ln -sfn ../vendor/vendor vendor
export CARGO_HOME=$BENCH_CACHE_DIR/cargo CARGO_NET_OFFLINE=true
cargo build --release --offline --jobs "$BENCH_JOBS"
