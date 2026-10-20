# Build environment "jax-power9": the ppc64le build host for Bazel-based
# Python/ML packages (jax, XLA). Sourced by scripts/script_worker/run.sh before
# the package's build.sh, its acceptance test and run_command_tool's commands;
# the model cannot change it, like the build hosts of OBS.
#
# It provides what an x86_64 build host gets from upstream binaries, which do
# not exist for ppc64le: Bazel 7.7.0 (compiled from its sources), clang 17,
# Python 3.12 with numpy/scipy, Java for Bazel, and the ppc64le wheels of
# numpy, ml-dtypes and zstandard (PyPI has none).
#
# It is made once, in the user's own directory, by `make setup-env
# ENV=jax-power9` (envs/jax-power9/setup.sh) in $BENCH_ENV_DIR, which the
# framework sets ($BENCH_HOME/envs/jax-power9). This script only exports it:
# it needs no root and changes nothing on the host.
# Exports: BAZEL, CLANG, PYTHON, TEST_PYTHON, LOCAL_WHEELS, JAVA_HOME.

_env=${BENCH_ENV_DIR:-}
if [ -z "$_env" ] || [ ! -f "$_env/.complete" ]; then
  echo "error: build environment jax-power9 is not set up${_env:+ in $_env}: run make setup-env ENV=jax-power9"
  return 1
fi

export JAVA_HOME=$(dirname "$(dirname "$(readlink -f "$_env/tools/bin/javac")")")
# Bazel, the compiler names python-build-standalone's sysconfig expects, and
# the environment's tools (clang, Python; Java, zip, patch, git...)
export PATH=$_env/bin:$_env/build/bin:$_env/tools/bin:$PATH
# the C++ runtime of the conda compilers, for the tools and wheels built with
# them (the host's is too old); only libstdc++ and libgcc_s, nothing else
export LD_LIBRARY_PATH=$_env/runtime-lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}
export BAZEL=$_env/bin/bazel-7.7.0
export CLANG=$_env/build/bin/clang
export PYTHON=$_env/build/bin/python
export TEST_PYTHON=$_env/test/bin/python
export LOCAL_WHEELS=$_env/wheels

echo "environment jax-power9 $(sed -n 's/.*"id": "\([0-9a-f]*\)".*/\1/p' "$_env/env.json") in $_env"
echo "BAZEL=$BAZEL ($($BAZEL --version 2>/dev/null))"
echo "CLANG=$CLANG ($($CLANG --version | head -1))"
echo "PYTHON=$PYTHON ($($PYTHON --version 2>&1)); TEST_PYTHON=$TEST_PYTHON (no jax installed; pytest)"
echo "LOCAL_WHEELS=$LOCAL_WHEELS: $(cd "$LOCAL_WHEELS" && ls *.whl | tr '\n' ' ')"
echo "BENCH_CACHE_DIR=${BENCH_CACHE_DIR:-} (build state of this run); BENCH_SHARED_CACHE_DIR=${BENCH_SHARED_CACHE_DIR:-} (shared caches)"
