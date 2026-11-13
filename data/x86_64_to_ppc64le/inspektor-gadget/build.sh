#!/bin/bash
# Build recipe for inspektor-gadget, as it builds on x86_64: its three
# programs, as the distribution builds them, with the modules vendored for it
# (../vendor), in the sources as the distribution unpacks them. It runs from
# the case directory in the environment envs/go-power9, with $BENCH_CACHE_DIR
# (this run's build state), $BENCH_SHARED_CACHE_DIR (caches kept across runs)
# and $BENCH_JOBS.
set -euo pipefail
cd inspektor-gadget
ln -sfn ../vendor vendor
export GOPATH=$BENCH_CACHE_DIR/go GOCACHE=$BENCH_CACHE_DIR/go-build GOFLAGS=-mod=vendor
go build -buildmode=pie -tags withoutebpf -o bin/kubectl-gadget ./cmd/kubectl-gadget
go build -buildmode=pie -tags withoutebpf -o bin/gadgetctl ./cmd/gadgetctl
go build -buildmode=pie -o bin/ig ./cmd/ig
