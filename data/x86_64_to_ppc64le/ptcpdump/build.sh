#!/bin/bash
# Build recipe for ptcpdump, as it builds on x86_64: its eBPF programs (make
# build-bpf), then the program linked with the system's libpcap (make build-
# dynamic-link), as the distribution builds them, with the modules vendored for
# it (../vendor), in the sources as the distribution unpacks them. It runs from
# the case directory in the environment envs/go-power9, with $BENCH_CACHE_DIR
# (this run's build state), $BENCH_SHARED_CACHE_DIR (caches kept across runs)
# and $BENCH_JOBS.
set -euo pipefail
cd ptcpdump
ln -sfn ../vendor vendor
export GOPATH=$BENCH_CACHE_DIR/go GOCACHE=$BENCH_CACHE_DIR/go-build GOFLAGS=-mod=vendor
make build-bpf VERSION=0.37.0
make build-dynamic-link VERSION=0.37.0
