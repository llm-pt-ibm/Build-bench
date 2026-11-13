#!/bin/bash
# Build recipe for kluctl, as it builds on x86_64: go build of cmd/main.go
# without cgo, as the distribution builds it on ppc64le, with the modules
# vendored for it (../vendor), in the sources as the distribution unpacks them.
# It runs from the case directory in the environment envs/go-power9, with
# $BENCH_CACHE_DIR (this run's build state), $BENCH_SHARED_CACHE_DIR (caches
# kept across runs) and $BENCH_JOBS.
set -euo pipefail
cd kluctl
ln -sfn ../vendor vendor
export GOPATH=$BENCH_CACHE_DIR/go GOCACHE=$BENCH_CACHE_DIR/go-build GOFLAGS=-mod=vendor
CGO_ENABLED=0 go build -buildmode=pie -o bin/kluctl ./cmd/main.go
