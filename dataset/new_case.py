"""Start a build-recipe case in one command: its sources, a build.sh for the
build system they use, a manifest.json, the skeleton of its acceptance test
and, unless the case uses an environment that exists, a build environment
(envs/<environment>/env.yaml) with that build system's packages.

Usage: python dataset/new_case.py <data_dir> <name> [--env <environment>] [--source [<dir>=]<url>]...
       python dataset/new_case.py --fetch <case_dir>     the sources again, e.g. after a clone
       (or: make new-case CASE=<name> [ENV=<environment>] [SOURCE="<url> ..."], make fetch CASE=<name>)
<url> is an archive of the sources (.tar.gz, .tar.xz, .tar.bz2, .tgz, .zip),
e.g. GitHub's https://github.com/<owner>/<repo>/archive/refs/tags/<tag>.tar.gz
or .../archive/<commit>.tar.gz. It is unpacked as <dir>/ in the case (default:
the project's name), recorded in manifest.json and ignored by git (the case's
.gitignore). The first source is the one build.sh builds; others (e.g. a
dependency the build takes from a local tree) are unpacked next to it.
RPM packages of openSUSE are fetched instead: dataset/fetch_package.py."""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
import zipfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
from tools.auto_repair import build_env  # noqa: E402

ARCHIVES = (".tar.gz", ".tgz", ".tar.xz", ".txz", ".tar.bz2", ".tbz2", ".tar.zst", ".tar", ".zip")
# conda's name of each machine, for the packages that carry it
CONDA_SUBDIR = {"ppc64le": "linux-ppc64le", "x86_64": "linux-64", "aarch64": "linux-aarch64", "s390x": "linux-s390x"}

BUILD_HEAD = """#!/bin/bash
# Build recipe for @NAME@: the build as it runs on @SOURCE_ARCH@. It runs from
# the case directory on the build host, in the build environment of
# manifest.json (envs/@ENV@/env.yaml, its tools in PATH), and the build succeeds
# when it exits with status 0.
#   $BENCH_CACHE_DIR         build state of this run (e.g. a Bazel output root)
#   $BENCH_SHARED_CACHE_DIR  caches later runs can reuse (downloads)
#   $BENCH_JOBS              number of parallel jobs
# make new-case wrote it for @SYSTEM@; adjust it to the package's build docs.
# Leave the artifacts where the acceptance test looks for them.
set -euo pipefail
"""

TEST_HEAD = """#!/bin/bash
# Acceptance test of @NAME@: does what build.sh built work? The framework runs
# it after every successful build, without network, on the build host in the
# case's build environment, with
#   $BENCH_SRC_DIR    the build copy of the case, with what build.sh left in it
#   $BENCH_CACHE_DIR  scratch space of the run
#   $BENCH_JOBS       number of parallel jobs
#   $TEST_PYTHON      the test environment's Python (with test_pip of env.yaml)
# It passes when it exits with status 0; the model can read it, not change it.
set -euo pipefail
src=$BENCH_SRC_DIR@SUBDIR@
"""

# build system: the files at the top of the sources that mark it, the conda
# packages of an environment for it, build.sh's commands (from the top of the
# sources) and the acceptance test's. In this order: the first that matches.
SYSTEMS = [
    {"name": "Bazel", "files": ["MODULE.bazel", "WORKSPACE", "WORKSPACE.bazel"],
     "conda": ["python=3.12", "pip", "clang=17.0.6", "clangxx=17.0.6", "lld=17.0.6",
               "libgcc-devel_@SUBDIR@=15.2.0", "libstdcxx-devel_@SUBDIR@=15.2.0"],
     "tools": ["openjdk=21", "zip", "unzip", "patch", "git", "which"],
     "build": """# TODO: the targets and options of the package's build docs (often after a
# configure step of its own); //... builds every target
"${BAZEL:-bazel}" --output_user_root="$BENCH_CACHE_DIR/bazel" build \\
  --disk_cache="$BENCH_SHARED_CACHE_DIR/bazel-disk" \\
  --repository_cache="$BENCH_SHARED_CACHE_DIR/bazel-repo" \\
  --jobs="$BENCH_JOBS" --keep_going \\
  //...
""",
     "test": """# TODO: install or run what the build left in $src (bazel-bin/) and check that it works
echo "TODO: test @NAME@"
exit 1
"""},
    {"name": "Python (pip)", "files": ["pyproject.toml", "setup.py"],
     "conda": ["python=3.12", "pip", "setuptools", "wheel", "cxx-compiler"],
     "build": """# a wheel in dist/, built as pip builds it (the build backend of pyproject.toml);
# pip takes the environment's own wheels ($LOCAL_WHEELS) before PyPI's
export PIP_CACHE_DIR=$BENCH_SHARED_CACHE_DIR/pip
if [ -n "${LOCAL_WHEELS:-}" ]; then export PIP_FIND_LINKS=$LOCAL_WHEELS; fi
"${PYTHON:-python3}" -m pip wheel --no-deps -w dist .
ls dist/*.whl
""",
     "test": """wheel=$(ls "$src"/dist/*.whl 2>/dev/null | head -1)
[ -n "$wheel" ] || { echo "error: the build left no wheel in dist/"; exit 1; }
echo "testing $(basename "$wheel")"
# a clean Python with the test environment's packages (test_pip: the
# package's dependencies, since there is no network)
venv=$BENCH_CACHE_DIR/acceptance-venv
rm -rf "$venv"
"${TEST_PYTHON:-python3}" -m venv --system-site-packages "$venv"
"$venv/bin/pip" install -q --no-deps --no-index "$wheel"
cd "$BENCH_CACHE_DIR"   # not the source tree, so that the installed package is imported
"$venv/bin/python" -c "import @MODULE@; print('@MODULE@', getattr(@MODULE@, '__version__', ''), 'imported')"
# TODO: check what @NAME@ does (or run its own tests, with pytest in test_pip)
"""},
    {"name": "CMake", "files": ["CMakeLists.txt"],
     "conda": ["cxx-compiler", "cmake", "make"],
     "build": """cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build --parallel "$BENCH_JOBS"
""",
     "test": """# the package's own tests (CTest)
ctest --test-dir "$src/build" --output-on-failure --no-tests=error -j "$BENCH_JOBS"
"""},
    {"name": "Meson", "files": ["meson.build"],
     "conda": ["cxx-compiler", "meson", "ninja", "pkg-config"],
     "build": """meson setup build --buildtype=release
meson compile -C build -j "$BENCH_JOBS"
""",
     "test": """# the package's own tests
meson test -C "$src/build" --print-errorlogs --num-processes "$BENCH_JOBS"
"""},
    {"name": "autotools", "files": ["configure", "configure.ac"],
     "conda": ["cxx-compiler", "autoconf", "automake", "libtool", "make", "pkg-config"],
     "build": """[ -x configure ] || autoreconf -fi
./configure
make -j "$BENCH_JOBS"
""",
     "test": """# the package's own tests
make -C "$src" -j "$BENCH_JOBS" check
"""},
    {"name": "Cargo", "files": ["Cargo.toml"],
     "conda": ["rust", "cxx-compiler"],
     "build": """export CARGO_HOME=$BENCH_CACHE_DIR/cargo   # also for the test, which has no network
cargo fetch                                # the crates of the tests too
cargo build --release --jobs "$BENCH_JOBS"
""",
     "test": """# the package's own tests
export CARGO_HOME=$BENCH_CACHE_DIR/cargo
cargo test --release --offline --jobs "$BENCH_JOBS" --manifest-path "$src/Cargo.toml"
"""},
    {"name": "Go", "files": ["go.mod"],
     "conda": ["go", "cxx-compiler"],
     "build": """export GOPATH=$BENCH_CACHE_DIR/go GOCACHE=$BENCH_CACHE_DIR/go-build GOFLAGS=-modcacherw
go mod download   # also what the tests use, since the test has no network
go build ./...
""",
     "test": """# the package's own tests
export GOPATH=$BENCH_CACHE_DIR/go GOCACHE=$BENCH_CACHE_DIR/go-build GOFLAGS=-modcacherw GOPROXY=off
cd "$src" && go test ./...
"""},
    {"name": "make", "files": ["Makefile", "GNUmakefile", "makefile"],
     "conda": ["cxx-compiler", "make"],
     "build": """make -j "$BENCH_JOBS"
""",
     "test": """# TODO: the package's own tests (make check, if it has them) or checks of what it built
make -C "$src" check
"""},
]
GENERIC = {"name": "no build system it knows", "files": [], "conda": None,
           "build": """echo "TODO: build @NAME@"
exit 1
""",
           "test": """echo "TODO: install the artifacts from $src and check that they work"
exit 1
"""}


def source_dir_name(url: str) -> str:
    """The directory a source archive is unpacked as: the project's name."""
    parts = [p for p in urllib.parse.urlparse(url).path.split("/") if p]
    if "archive" in parts:   # GitHub, GitLab: <owner>/<repo>/archive/<ref>.tar.gz
        before = [p for p in parts[:parts.index("archive")] if p != "-"]
        if before:
            return before[-1]
    base = parts[-1] if parts else "src"
    for ext in ARCHIVES:
        if base.endswith(ext):
            base = base[:-len(ext)]
            break
    return re.sub(r"[-_]v?\d[0-9A-Za-z.+]*$", "", base) or base


def version_of(url: str) -> str:
    found = re.search(r"(?:^|[-_/v])(\d+(?:\.\d+)+)(?:[-_.][0-9A-Za-z]+)*$",
                      re.sub(r"(\.tar)?\.(gz|xz|bz2|zst|tgz|txz|tbz2|zip|tar)$", "",
                             urllib.parse.urlparse(url).path))
    return found.group(1) if found else ""


def fetch(case_dir: str, dirname: str, url: str) -> bool:
    """Unpack the archive at url as case_dir/dirname (False if it is there)."""
    dest = os.path.join(case_dir, dirname)
    if os.path.exists(dest):
        return False
    os.makedirs(case_dir, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix=".fetch-", dir=case_dir)
    try:
        archive = os.path.join(tmp, "archive")
        print(f"downloading {url}", flush=True)
        request = urllib.request.Request(url, headers={"User-Agent": "build-bench"})
        try:
            with urllib.request.urlopen(request, timeout=600) as r, open(archive, "wb") as f:
                shutil.copyfileobj(r, f, 1 << 20)
        except (OSError, ValueError) as e:   # URLError, HTTPError (404...), a bad URL
            raise SystemExit(f"error: downloading {url}: {e}")
        out = os.path.join(tmp, "out")
        os.makedirs(out)
        if zipfile.is_zipfile(archive):
            with zipfile.ZipFile(archive) as z:
                for info in z.infolist():
                    path = z.extract(info, out)
                    if info.external_attr >> 16 & 0o777:   # the modes zip keeps (executables)
                        os.chmod(path, info.external_attr >> 16 & 0o777)
        else:
            subprocess.run(["tar", "-xf", archive, "-C", out], check=True)
        entries = os.listdir(out)
        # an archive of one directory (<project>-<version>/) is that directory
        top = os.path.join(out, entries[0]) if len(entries) == 1 else out
        os.rename(top if os.path.isdir(top) else out, dest)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"  unpacked as {dirname}/", flush=True)
    return True


def ignore(case_dir: str, dirnames: list) -> str:
    """The case's .gitignore lists the downloaded sources (make fetch recreates them)."""
    path = os.path.join(case_dir, ".gitignore")
    lines = open(path).read().splitlines() if os.path.exists(path) else \
        ["# sources downloaded by make new-case; make fetch downloads them again"]
    lines += [f"/{d}/" for d in dirnames if f"/{d}/" not in lines]
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")
    return path


def build_system(src: str) -> dict:
    names = set(os.listdir(src)) if os.path.isdir(src) else set()
    return next((s for s in SYSTEMS if names & set(s["files"])), GENERIC)


def python_module(src: str, name: str) -> str:
    """The module a Python package's wheel installs, by its name (pyproject.toml)."""
    try:
        import tomllib
        with open(os.path.join(src, "pyproject.toml"), "rb") as f:
            name = tomllib.load(f).get("project", {}).get("name") or name
    except (ImportError, OSError, ValueError):
        pass
    return re.sub(r"^python[-_]", "", name).lower().replace("-", "_").replace(".", "_")


def environment_values(system: dict, src: str, target_arch: str) -> dict:
    """The keys of a new env.yaml for the build system (None: the example's)."""
    if not system["conda"]:
        return {}
    subdir = CONDA_SUBDIR.get(target_arch, f"linux-{target_arch}")
    values = {"conda": [p.replace("@SUBDIR@", subdir) for p in system["conda"]]}
    if system.get("tools"):
        values["tools"] = system["tools"]
    if system["name"] == "Bazel":
        try:   # the version the sources ask for
            with open(os.path.join(src, ".bazelversion")) as f:
                values["bazel"] = f.read().split()[0]
        except (OSError, IndexError):
            values["bazel"] = "7.7.0"
    return values


def new_case(data_dir: str, name: str, environment: str = "", sources: list = ()) -> dict:
    """Make the case: what it created (files and directories), its
    environment, whether that was created too, and the build system found."""
    direction = os.path.basename(os.path.normpath(data_dir))
    source_arch, _, target_arch = direction.partition("_to_")
    case = os.path.join(data_dir, name)
    if os.path.exists(case):
        raise SystemExit(f"error: {os.path.relpath(case, ROOT)} exists already")
    named = {}
    for item in sources:
        dirname, sep, url = item.partition("=")
        if not sep or "/" in dirname or ":" in dirname:
            dirname, url = source_dir_name(item), item
        if dirname in named:
            raise SystemExit(f"error: two sources unpack as {dirname}/: name one, e.g. SOURCE=\"{dirname}2=<url>\"")
        named[dirname] = url
    os.makedirs(case)
    created = []
    try:
        for dirname, url in named.items():
            fetch(case, dirname, url)
            created.append(os.path.join(case, dirname))
    except BaseException:   # a failed download (SystemExit) or Ctrl-C: no half-made case
        shutil.rmtree(case, ignore_errors=True)
        raise
    main_src = next(iter(named), "")
    src = os.path.join(case, main_src) if main_src else case
    system = build_system(src) if main_src else GENERIC

    environment = environment or name
    env_created = not build_env.exists(environment)
    if env_created:
        created.append(build_env.new(environment, environment_values(system, src, target_arch)))

    def fill(text):
        return (text.replace("@NAME@", name).replace("@ENV@", environment).replace("@SYSTEM@", system["name"])
                .replace("@SOURCE_ARCH@", source_arch or "the source architecture")
                .replace("@SUBDIR@", f"/{main_src}" if main_src else "")
                .replace("@MODULE@", python_module(src, name)))

    build = fill(BUILD_HEAD) + (f"cd {main_src}\n" if main_src else "") + fill(system["build"])
    with open(os.path.join(case, "build.sh"), "w") as f:
        f.write(build)
    os.chmod(os.path.join(case, "build.sh"), 0o755)
    task = {"package": name, "direction": direction, "type": "recipe", "sources": named}
    versions = [v for v in (version_of(u) for u in named.values()) if v]
    if versions:
        task["version"] = versions[0]
    with open(os.path.join(case, "manifest.json"), "w") as f:
        json.dump({"task": task, "environment": environment, "version": 1}, f, indent=2)
        f.write("\n")
    created[:0] = [os.path.join(case, "build.sh"), os.path.join(case, "manifest.json")]
    if named:
        created.append(ignore(case, list(named)))
    test = os.path.join(ROOT, "acceptance", direction, f"{name}.sh")
    if not os.path.exists(test):
        os.makedirs(os.path.dirname(test), exist_ok=True)
        with open(test, "w") as f:
            f.write(fill(TEST_HEAD) + fill(system["test"]))
        os.chmod(test, 0o755)
        created.insert(2, test)
    return {"created": created, "environment": environment, "env_created": env_created, "system": system["name"]}


def fetch_case(case_dir: str) -> None:
    """The sources of manifest.json again (its fetch script, if it names one)."""
    with open(os.path.join(case_dir, "manifest.json")) as f:
        manifest = json.load(f)
    if manifest.get("fetch"):
        sys.exit(subprocess.call(["bash", os.path.join(ROOT, manifest["fetch"]), case_dir], cwd=ROOT))
    sources = {d: u for d, u in ((manifest.get("task") or {}).get("sources") or {}).items()
               if re.match(r"^(https?|ftp|file)://", str(u))}
    if not sources:
        sys.exit(f"error: {os.path.relpath(case_dir, ROOT)}/manifest.json names no sources to download")
    for dirname, url in sources.items():
        if not fetch(case_dir, dirname, url):
            print(f"  {dirname}/ is there already")
    ignore(case_dir, list(sources))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("data_dir", nargs="?")
    parser.add_argument("name", nargs="?")
    parser.add_argument("--env", default="")
    parser.add_argument("--source", action="append", default=[], help="[<dir>=]<url> of an archive of the sources")
    parser.add_argument("--fetch", metavar="CASE_DIR", help="download the sources of manifest.json again")
    args = parser.parse_args()
    if args.fetch:
        return fetch_case(args.fetch)
    if not args.name:
        parser.error("data_dir and name are needed")
    made = new_case(args.data_dir, args.name, args.env, args.source)
    environment, system = made["environment"], made["system"]
    direction = os.path.basename(os.path.normpath(args.data_dir))
    rel = os.path.relpath
    print("created:\n" + "\n".join(f"  {rel(p, ROOT)}{'/' if os.path.isdir(p) else ''}" for p in made["created"]))
    steps = []
    if not args.source:
        steps.append("put the sources next to build.sh (or start again with SOURCE=<url of an archive>)")
    if made["env_created"]:
        steps.append(f"check envs/{environment}/env.yaml (written for {system}), then make setup-env ENV={environment}")
    elif not os.path.isfile(os.path.join(build_env.env_dir(environment), ".complete")):
        steps.append(f"make setup-env ENV={environment}")
    steps += [f"build.sh: the build as upstream runs it on {direction.split('_to_')[0]}",
              f"acceptance/{direction}/{args.name}.sh: check that what it built works",
              f"make baseline CASE={args.name}   (the original failure: log_failed.txt)",
              f"make check-case CASE={args.name}"]
    print(f"\nbuild system: {system}\nnext steps:\n" + "\n".join(f"  {i}. {s}" for i, s in enumerate(steps, 1)))


if __name__ == "__main__":
    main()
