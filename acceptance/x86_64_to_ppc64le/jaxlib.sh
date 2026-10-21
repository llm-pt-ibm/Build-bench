#!/bin/bash
# Acceptance test of jaxlib: install the built wheel with jax (from the same
# source tree) in a clean Python and check that it works, with the checks of
# jaxlib_checks.py: numerics against NumPy per dtype (float32, float64,
# float16, bfloat16, int8, also inside jit-compiled kernels), linear algebra,
# FFT and convolution, gradients, PRNG streams bit-identical to x86_64 and a
# small training run. Each check runs in its own process, so a crash in one is
# reported and the others still run. Then a subset of JAX's own test suite
# (tests/random_test.py, linalg_test.py, nn_test.py) must pass.
set -uo pipefail
here=$(dirname "$(readlink -f "$0")")
wheel=$(ls "$BENCH_SRC_DIR"/jax/dist/jaxlib-*.whl 2>/dev/null | head -1)
[ -n "$wheel" ] || { echo "error: the build left no jaxlib wheel in jax/dist"; exit 1; }
echo "testing $(basename "$wheel")"
venv=$BENCH_CACHE_DIR/acceptance-venv
rm -rf "$venv"
"$TEST_PYTHON" -m venv --system-site-packages "$venv" || exit 1
# pip builds jax in its source tree, in setuptools' jax/build/lib and
# jax/build/bdist.*: start from none (what an earlier test, or the case's
# own copy, left there made the build of the jax wheel fail)
rm -rf "$BENCH_SRC_DIR"/jax/build/lib "$BENCH_SRC_DIR"/jax/build/bdist.*
"$venv/bin/pip" install -q --no-deps --no-build-isolation "$wheel" "$BENCH_SRC_DIR/jax" \
  || { echo "error: installing the wheel failed"; exit 1; }
cd "$BENCH_CACHE_DIR"   # not the source tree, so that jax is imported from the venv
failed=0
for check in $("$venv/bin/python" "$here/jaxlib_checks.py" --list); do
  out=$(timeout 900 "$venv/bin/python" "$here/jaxlib_checks.py" "$check" 2>&1)
  rc=$?
  if [ $rc -eq 0 ]; then
    echo "PASS $check"
  else
    echo "FAIL $check (exit status $rc$([ $rc -eq 134 ] && echo ', aborted')$([ $rc -eq 139 ] && echo ', segmentation fault'))"
    echo "$out" | grep -v "^    @ " | tail -20 | sed 's/^/    /'
    failed=$((failed + 1))
  fi
done
echo "=== JAX test suite: tests/random_test.py tests/linalg_test.py tests/nn_test.py"
jobs=${BENCH_JOBS:-48}; [ "$jobs" -gt 48 ] && jobs=48
log=$BENCH_CACHE_DIR/jax_tests.log
(cd "$BENCH_SRC_DIR/jax" && timeout 2400 "$venv/bin/python" -P -m pytest -q -n "$jobs" -p no:cacheprovider \
  tests/random_test.py tests/linalg_test.py tests/nn_test.py) > "$log" 2>&1
rc=$?
summary=$(grep -E "^[0-9]+ (passed|failed)|^=+ .*(passed|failed|error).* =+$" "$log" | tail -1)
if [ $rc -eq 0 ]; then
  echo "PASS jax_test_suite: $summary"
else
  echo "FAIL jax_test_suite (exit status $rc): ${summary:-no summary, see below}"
  grep -E "^(FAILED|ERROR) " "$log" | head -20 | sed 's/^/    /'
  grep -oE "worker '[^']*' crashed while running '[^']*'" "$log" | head -20 | sed 's/^/    /'
  grep -E "LLVM ERROR|Segmentation fault" "$log" | sort -u | head -5 | sed 's/^/    /'
  # a crashed pytest worker loses the test's error output: run a few of the
  # crashed tests alone, without output capture, to show why they crash
  for t in $(grep -oE "crashed while running '[^']*'" "$log" | sed "s/.*running '//; s/'\$//" | head -2); do
    echo "    --- $t, run alone:"
    (cd "$BENCH_SRC_DIR/jax" && timeout 600 "$venv/bin/python" -P -m pytest -q -s -p no:cacheprovider -p no:xdist "$t" 2>&1) \
      | grep -E "LLVM ERROR|Cannot select|Check failed|^E |^[FE][0-9]{4} |@ .*(llvm::|xla::|PPC|X86|AArch64)" | head -12 | sed 's/^/        /'
  done
  [ -z "$summary" ] && tail -30 "$log" | sed 's/^/    /'
  failed=$((failed + 1))
fi
echo "acceptance: $failed check(s) failed"
[ "$failed" -eq 0 ]
