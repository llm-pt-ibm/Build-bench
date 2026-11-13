#!/bin/bash
# Build recipe for python-mitmproxy-wireguard, as it builds on x86_64: a wheel
# built with maturin (pip, no build isolation), with the crates vendored for it
# (../vendor), unpacked into the sources as the distribution does. It runs from
# the case directory in the environment envs/rust-power9, with $BENCH_CACHE_DIR
# (this run's build state), $BENCH_SHARED_CACHE_DIR (caches kept across runs)
# and $BENCH_JOBS.
set -euo pipefail
cd mitmproxy_wireguard
cp -a ../vendor/Cargo.lock .
mkdir -p .cargo
printf '[source.crates-io]\nreplace-with = "vendored-sources"\n\n[source.vendored-sources]\ndirectory = "vendor"\n' > .cargo/config.toml
ln -sfn ../vendor/vendor vendor
export CARGO_HOME=$BENCH_CACHE_DIR/cargo CARGO_NET_OFFLINE=true
"${PYTHON:-python3}" -m pip wheel --no-deps --no-build-isolation -w dist .
ls dist/*.whl
