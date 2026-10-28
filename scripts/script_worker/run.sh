#!/bin/bash
# Run the recipe (build.sh) of a build-recipe case on this host: set up the
# build environment the case declares, then run build.sh from the package root.
# Usage: scripts/script_worker/run.sh <source_dir> [environment_script] [script]
#   script: run this script instead of build.sh (e.g. an acceptance test)
# The exit status is that of the script (2 if the environment cannot be set up).
set -uo pipefail
src=$1
env_script=${2:-}
if [ -n "${BENCH_PROXY_SOCKET:-}" ]; then
  # no network but the framework's proxy (tools/auto_repair/net_proxy.py),
  # which lets the build reach any host and logs every connection
  py=$(command -v python3 || echo /usr/libexec/platform-python)
  coproc forward { exec "$py" "$(dirname "$0")/proxy_forward.py" "$BENCH_PROXY_SOCKET" 3128; }
  read -r -t 10 ready <&"${forward[0]}" || ready=
  [ "$ready" = ready ] || { echo "error: the build's network proxy did not start"; exit 2; }
  proxy=http://127.0.0.1:3128
  export http_proxy=$proxy https_proxy=$proxy HTTP_PROXY=$proxy HTTPS_PROXY=$proxy
  export no_proxy=localhost,127.0.0.1,::1 NO_PROXY=localhost,127.0.0.1,::1
  echo "=== network: through the build host's proxy, which logs every connection"
fi
if [ -n "$env_script" ]; then
  echo "=== build environment: $(basename "$env_script" .sh)"
  # shellcheck disable=SC1090
  source "$env_script" || { echo "error: the build environment could not be set up"; exit 2; }
fi
script=${3:-./build.sh}
echo "=== build host: $(uname -m), $(nproc) cpus, ${BENCH_JOBS:-?} jobs"
echo "=== running $script"
cd "$src" && exec bash "$script"
