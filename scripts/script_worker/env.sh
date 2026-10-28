# Exports the build environment of a recipe case ($BENCH_ENV_DIR, made by make
# setup-env): PATH, LD_LIBRARY_PATH, PYTHON, TEST_PYTHON, CLANG, BAZEL,
# JAVA_HOME, LOCAL_WHEELS and the variables of env.yaml's env. run.sh sources
# it before build.sh, the acceptance test and run_command_tool's commands.
_env=${BENCH_ENV_DIR:-}
_name=$(basename "${_env:-environment}")
if [ -z "$_env" ] || [ ! -f "$_env/.complete" ]; then
  echo "error: build environment $_name is not set up${_env:+ in $_env}: run make setup-env ENV=$_name"
  return 1
fi
_path=$_env/bin:$_env/build/bin
if [ -d "$_env/tools/bin" ]; then _path=$_path:$_env/tools/bin; fi
export PATH=$_path:$PATH
if [ -d "$_env/runtime-lib" ]; then
  export LD_LIBRARY_PATH=$_env/runtime-lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}
fi
if [ -x "$_env/build/bin/python" ]; then export PYTHON=$_env/build/bin/python; fi
if [ -x "$_env/test/bin/python" ]; then export TEST_PYTHON=$_env/test/bin/python; fi
if [ -x "$_env/build/bin/clang" ]; then export CLANG=$_env/build/bin/clang; fi
for _b in "$_env"/bin/bazel-*; do
  if [ -x "$_b" ]; then export BAZEL=$_b; fi
done
for _j in "$_env/tools/bin/javac" "$_env/build/bin/javac"; do
  if [ -e "$_j" ]; then export JAVA_HOME=$(dirname "$(dirname "$(readlink -f "$_j")")"); break; fi
done
if ls "$_env"/wheels/*.whl >/dev/null 2>&1; then export LOCAL_WHEELS=$_env/wheels; fi
if [ -f "$_env/exports.sh" ]; then . "$_env/exports.sh"; fi

echo "environment $_name $(sed -n 's/^ "id": "\([0-9a-f]*\)".*/\1/p' "$_env/env.json" 2>/dev/null) in $_env"
if [ -n "${PYTHON:-}" ]; then
  echo "PYTHON=$PYTHON ($("$PYTHON" --version 2>&1))${TEST_PYTHON:+; TEST_PYTHON=$TEST_PYTHON}"
fi
if [ -n "${CLANG:-}" ]; then echo "CLANG=$CLANG ($("$CLANG" --version | head -1))"; fi
if [ -n "${BAZEL:-}" ]; then echo "BAZEL=$BAZEL ($("$BAZEL" --version 2>/dev/null))"; fi
if [ -n "${JAVA_HOME:-}" ]; then echo "JAVA_HOME=$JAVA_HOME"; fi
if [ -n "${LOCAL_WHEELS:-}" ]; then
  echo "LOCAL_WHEELS=$LOCAL_WHEELS: $(cd "$LOCAL_WHEELS" && ls *.whl 2>/dev/null | tr '\n' ' ')"
fi
if [ -f "$_env/exports.sh" ]; then
  for _v in $(sed -n 's/^export \([A-Za-z_][A-Za-z0-9_]*\)=.*/\1/p' "$_env/exports.sh"); do
    eval "echo \"$_v=\${$_v}\""
  done
fi
echo "BENCH_CACHE_DIR=${BENCH_CACHE_DIR:-} (build state of this run); BENCH_SHARED_CACHE_DIR=${BENCH_SHARED_CACHE_DIR:-} (shared caches)"
unset _env _name _path _b _j _v
true
