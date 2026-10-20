#!/bin/bash
# Set up build environment "jax-power9" once, in $BENCH_ENV_DIR (by default
# $BENCH_HOME/envs/jax-power9): what the jaxlib case's build.sh and acceptance
# test use, in the user's own directory. It needs no root and changes nothing
# on the host. Run by `make setup-env ENV=jax-power9`; running it again skips
# what is done (delete the directory to start over).
#
# Needs: conda (Miniforge; CONDA=/path/to/conda, else mamba/conda in PATH or
# ~/miniforge3/bin/conda), network access, and a C/C++ compiler on the host
# for compiling Bazel. Options:
#   BAZEL_BINARY=<file>  use this Bazel 7.7.0 instead of compiling it from its
#                        sources (Bazel 7.1.0, then 7.7.0 with it: about 15 minutes)
#   WHEELS_FROM=<dir>    copy the ppc64le wheels from this directory instead
#                        of building them
#
# Layout:  build/  conda environment of the build (Python, clang 17)
#          tools/  conda environment of what Bazel needs (Java 21, zip, patch, git)
#          test/   conda environment of the acceptance test (no jax installed)
#          bin/    Bazel 7.7.0 and the compiler names Python's sysconfig expects
#          runtime-lib/  the C++ runtime of the conda compilers (newer than the host's)
#          wheels/ ppc64le wheels PyPI lacks
#          env.json  what the environment is (versions, checksums), recorded in results
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
dir=${BENCH_ENV_DIR:?set BENCH_ENV_DIR (make setup-env does)}
conda=${CONDA:-$(command -v mamba || command -v conda || echo "$HOME/miniforge3/bin/conda")}
[ -x "$conda" ] || { echo "error: conda not found: install Miniforge or set CONDA=/path/to/conda"; exit 1; }
mkdir -p "$dir/bin" "$dir/runtime-lib" "$dir/wheels" "$dir/src"
step() { echo; echo "=== $* ($(date +%H:%M:%S))"; }
packages() { grep -v '^\s*#' "$1" | grep -v '^\s*$'; }
# a conda environment from its lock file (exact packages, no solving), or else
# solved from the list of packages
conda_env() {   # <prefix> <name: build or tools>
  if [ -f "$here/$2.lock" ]; then
    "$conda" create -y -q -p "$1" --file "$here/$2.lock"
  else
    "$conda" create -y -q -p "$1" --override-channels -c conda-forge $(packages "$here/${2/build/conda}.txt")
  fi
}

if [ ! -x "$dir/build/bin/python" ]; then
  step "build environment: $dir/build"
  conda_env "$dir/build" build
fi
if [ ! -x "$dir/tools/bin/javac" ]; then
  step "tools environment: $dir/tools"
  conda_env "$dir/tools" tools
fi
java_home=$(dirname "$(dirname "$(readlink -f "$dir/tools/bin/javac")")")

# the C++ runtime of the conda compilers: the tools and wheels built with them
# need it, and the host's (RHEL 8: gcc 8.5) is too old
for lib in libstdc++.so.6 libgcc_s.so.1; do
  ln -sf "$dir/build/lib/$lib" "$dir/runtime-lib/$lib"
done
# the compiler names the sysconfig of python-build-standalone (rules_python's
# hermetic Python) expects
ln -sf "$dir/build/bin/clang" "$dir/bin/powerpc64le-linux-gnu-gcc"
ln -sf "$dir/build/bin/clang++" "$dir/bin/powerpc64le-linux-gnu-g++"

if [ ! -x "$dir/bin/bazel-7.7.0" ]; then
  if [ -n "${BAZEL_BINARY:-}" ]; then
    step "Bazel 7.7.0 from $BAZEL_BINARY"
    cp "$BAZEL_BINARY" "$dir/bin/bazel-7.7.0.tmp"
  else
    # No Bazel 7 for ppc64le upstream, and conda-forge stops at 6.x. Bazel
    # 7.7.0's own bootstrap (compile.sh) fails ("name 'macro' is not defined",
    # bazelbuild/bazel#27349), so Bazel 7.1.0 is bootstrapped from its sources
    # and builds 7.7.0, as for the team's manual port. Java, zip and unzip come
    # from the tools environment, python3 (Bazel runs Python tools) from the
    # build environment, the C/C++ compiler from the host.
    export JAVA_HOME="$java_home" PATH="$dir/tools/bin:$dir/build/bin:$PATH"
    for v in 7.1.0 7.7.0; do
      [ -f "$dir/src/bazel-$v-dist.zip" ] || curl -fsSL -o "$dir/src/bazel-$v-dist.zip" \
        "https://github.com/bazelbuild/bazel/releases/download/$v/bazel-$v-dist.zip"
    done
    if [ ! -x "$dir/src/bazel-7.1.0/output/bazel" ]; then
      step "Bazel 7.1.0 from its sources (to build 7.7.0)"
      rm -rf "$dir/src/bazel-7.1.0" && mkdir "$dir/src/bazel-7.1.0"
      (cd "$dir/src/bazel-7.1.0" && unzip -q ../bazel-7.1.0-dist.zip &&
       env EXTRA_BAZEL_ARGS="--host_javabase=@local_jdk//:jdk --local_ram_resources=HOST_RAM*.5" \
           bash ./compile.sh)
    fi
    step "Bazel 7.7.0, built with 7.1.0"
    rm -rf "$dir/src/bazel-7.7.0" && mkdir "$dir/src/bazel-7.7.0"
    (cd "$dir/src/bazel-7.7.0" && unzip -q ../bazel-7.7.0-dist.zip &&
     "$dir/src/bazel-7.1.0/output/bazel" --output_user_root="$dir/src/bazel-out" build \
         --local_ram_resources=HOST_RAM*.5 --embed_label=7.7.0 //src:bazel_nojdk &&
     cp bazel-bin/src/bazel_nojdk "$dir/bin/bazel-7.7.0.tmp" &&
     "$dir/src/bazel-7.1.0/output/bazel" --output_user_root="$dir/src/bazel-out" shutdown)
    # the sources and build trees are not needed any more (several GB; Bazel
    # leaves its output trees read-only)
    chmod -R u+w "$dir/src" 2>/dev/null || true
    rm -rf "$dir/src/bazel-out" "$dir/src/bazel-7.1.0" "$dir/src/bazel-7.7.0"
  fi
  chmod +x "$dir/bin/bazel-7.7.0.tmp" && mv "$dir/bin/bazel-7.7.0.tmp" "$dir/bin/bazel-7.7.0"
fi

if [ ! -f "$dir/wheels/.complete" ]; then
  if [ -n "${WHEELS_FROM:-}" ]; then
    step "wheels from $WHEELS_FROM"
    for w in $(packages "$here/wheels.txt"); do
      cp "$WHEELS_FROM"/"$(echo "${w%%==*}" | tr - _)"-"${w##*==}"-*.whl "$dir/wheels/"
    done
  else
    step "ppc64le wheels: $(packages "$here/wheels.txt" | tr '\n' ' ')"
    env PATH="$dir/bin:$dir/build/bin:$dir/tools/bin:$PATH" LD_LIBRARY_PATH="$dir/runtime-lib" CC=clang CXX=clang++ \
      "$dir/build/bin/python" -m pip wheel -q --no-deps -w "$dir/wheels" $(packages "$here/wheels.txt")
  fi
  touch "$dir/wheels/.complete"
fi

if ! "$dir/build/bin/python" -c "import ml_dtypes, opt_einsum" 2>/dev/null; then
  step "Python packages of the build environment"
  "$dir/build/bin/python" -m pip install -q --no-deps "$dir"/wheels/ml_dtypes-*.whl opt-einsum==3.4.0
fi
if [ ! -x "$dir/test/bin/python" ]; then
  step "test environment: $dir/test (no jax: the test installs the wheel it checks)"
  conda_env "$dir/test" build
  "$dir/test/bin/python" -m pip install -q --no-deps "$dir"/wheels/ml_dtypes-*.whl
  "$dir/test/bin/python" -m pip install -q $(packages "$here/test-pip.txt")
fi

step "env.json"
"$dir/build/bin/python" - "$dir" "$conda" <<'EOF'
import hashlib, json, os, subprocess, sys
d, conda = sys.argv[1], sys.argv[2]
def listing(prefix):
    out = subprocess.run([conda, "list", "-p", prefix, "--json"], capture_output=True, text=True, check=True)
    return {p["name"]: p["version"] for p in json.loads(out.stdout)}
def sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()
bazel = os.path.join(d, "bin", "bazel-7.7.0")
info = {"name": "jax-power9",
        "build": listing(os.path.join(d, "build")), "tools": listing(os.path.join(d, "tools")),
        "test": listing(os.path.join(d, "test")),
        "bazel": {"version": "7.7.0", "sha256": sha(bazel)},
        "wheels": {w: sha(os.path.join(d, "wheels", w)) for w in sorted(os.listdir(os.path.join(d, "wheels")))
                   if w.endswith(".whl")}}
info["id"] = hashlib.sha256(json.dumps(info, sort_keys=True).encode()).hexdigest()[:12]
json.dump(info, open(os.path.join(d, "env.json"), "w"), indent=1)
print(f"environment jax-power9 {info['id']}: {len(info['build'])} build packages, "
      f"{len(info['test'])} test packages, {len(info['wheels'])} wheels")
EOF
touch "$dir/.complete"
echo "ready: $dir"
