"""Build environments of build-recipe cases: what a case's build.sh, its
acceptance test and run_command_tool's commands run with, as the build hosts of
OBS are for RPM packages. An environment is one file, envs/<name>/env.yaml,
for any package and build system; `make setup-env ENV=<name>` makes it once
in BENCH_HOME/envs/<name>, in the user's own directory (no root).
envs/env.example.yaml shows every key, and `make new-env ENV=<name>` copies it.

env.yaml (every key is optional, at least one is needed):
  conda      conda packages of the build environment: the compilers, build
             tools, libraries and interpreters build.sh uses (CMake, Rust, Go,
             Java, Python...)
  channels   conda channels, in order (default: conda-forge)
  tools      conda packages of a separate tools environment, for tools whose
             dependencies conflict with the build's (e.g. Java for Bazel)
  system     RHEL 8 packages (dnf) added to the image builds run in
  env        variables exported to builds, tests and commands, and set while
             setup builds the wheels and runs setup; $BENCH_ENV_DIR is the
             environment's directory
  setup      commands run once at the end of setup, in the environment's
             directory with its tools in PATH, for what no other key covers
             (e.g. a tool compiled from its sources into $BENCH_ENV_DIR/bin)
  bazel      a Bazel version, compiled from its sources (none is published for
             ppc64le); compiled once per version and shared by the environments
  wheels     Python wheels PyPI lacks for this architecture, built with the
             environment's compilers ($LOCAL_WHEELS)
  build_pip  pip packages of the build environment
  test_pip   pip packages of the test environment, a copy of the build
             environment without the package the case builds: what the
             acceptance test imports, since it runs without network
In build_pip and test_pip, a name among wheels is installed from the wheel the
environment built; the three Python keys need a Python in conda.

The first setup writes envs/<name>/build.lock (and tools.lock): the exact
packages conda chose, which later setups install, so the environment can be
made again; commit them with env.yaml. Setup skips what is done, and ends with
env.json (versions and checksums, recorded in every result) and .complete.
At run time scripts/script_worker/env.sh exports the environment (PATH,
PYTHON, TEST_PYTHON, CLANG, BAZEL, JAVA_HOME, LOCAL_WHEELS, and env); an
envs/<name>.sh replaces it for an environment that needs more. The image is
envs/<name>/Containerfile, or envs/Containerfile, with the system packages."""
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import time
import urllib.request

import yaml

from tools.auto_repair.paths import bench_home, env_dir

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
ENVS_DIR = os.path.join(ROOT, "envs")
GENERIC_SCRIPT = os.path.join(ROOT, "scripts", "script_worker", "env.sh")
EXAMPLE = os.path.join(ROOT, "envs", "env.example.yaml")
LISTS = ("conda", "channels", "tools", "system", "setup", "wheels", "build_pip", "test_pip")
KEYS = LISTS + ("env", "bazel", "bazel_bootstrap")
# Bazel versions whose own bootstrap (compile.sh) fails: an older version is
# bootstrapped from its sources and builds them (7.7.0: "name 'macro' is not
# defined", bazelbuild/bazel#27349); env.yaml's bazel_bootstrap overrides it
BAZEL_BOOTSTRAP = {"7.7.0": "7.1.0"}
# the compiler names the sysconfig of python-build-standalone (rules_python's
# hermetic Python) expects, per machine
TRIPLETS = {"ppc64le": "powerpc64le-linux-gnu", "x86_64": "x86_64-linux-gnu", "aarch64": "aarch64-linux-gnu",
            "s390x": "s390x-linux-gnu"}


def spec_file(name: str) -> str:
    return os.path.join(ENVS_DIR, name, "env.yaml")


def exists(name: str) -> bool:
    return os.path.isfile(spec_file(name)) or os.path.isfile(os.path.join(ENVS_DIR, f"{name}.sh"))


def env_script(name: str) -> str:
    """What builds, tests and commands source: envs/<name>.sh, or the generic script."""
    own = os.path.join(ENVS_DIR, f"{name}.sh")
    return own if os.path.isfile(own) else GENERIC_SCRIPT


def new(name: str, values: dict = None) -> str:
    """envs/<name>/env.yaml from the example, to edit; values set keys of it
    (make new-case: the packages of the case's build system), each on the
    line of the example that shows it."""
    path = spec_file(name)
    if os.path.exists(path):
        raise SystemExit(f"error: {os.path.relpath(path, ROOT)} exists already")
    with open(EXAMPLE) as f:
        text = f.read()
    for key, value in (values or {}).items():
        line = f"{key}: " + (f"[{', '.join(map(str, value))}]" if isinstance(value, list) else str(value))
        text, found = re.subn(rf"^(# )?{key}:.*$", lambda _: line, text, count=1, flags=re.M)
        if not found:
            text += line + "\n"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)
    return path


def load(name: str) -> dict:
    path = spec_file(name)
    if not os.path.isfile(path):
        raise SystemExit(f"error: no environment {os.path.relpath(path, ROOT)} "
                         f"(make new-env ENV={name} starts one from the example)")
    return load_file(path)


def load_file(path: str) -> dict:
    where = os.path.relpath(path, ROOT) if path.startswith(ROOT + os.sep) else path

    def fail(message):
        raise SystemExit(f"error: {where}: {message} (envs/env.example.yaml shows every key)")

    with open(path) as f:
        spec = yaml.safe_load(f) or {}
    if not isinstance(spec, dict):
        fail("not a mapping of keys")
    unknown = sorted(set(spec) - set(KEYS))
    if unknown:
        fail(f"unknown keys {', '.join(unknown)} (known: {', '.join(KEYS)})")
    for key in LISTS:
        value = spec.get(key) or []
        if not isinstance(value, list):
            fail(f"{key} is a list, e.g. {key}: [a, b]")
        spec[key] = [str(v) for v in value]
    env = spec.get("env") or {}
    if not isinstance(env, dict) or not all(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", str(k)) for k in env):
        fail("env maps variable names to values, e.g. env: {CC: clang}")
    spec["env"] = {str(k): str(v) for k, v in env.items()}
    spec["channels"] = spec["channels"] or ["conda-forge"]
    python_keys = [k for k in ("wheels", "build_pip", "test_pip") if spec[k]]
    if python_keys and not spec["conda"]:
        fail(f"{', '.join(python_keys)} need a Python in conda")
    if not any(spec.get(k) for k in ("conda", "tools", "system", "setup", "bazel", "env")):
        fail("nothing to set up")
    return spec


def _step(text: str) -> None:
    print(f"\n=== {text} ({time.strftime('%H:%M:%S')})", flush=True)


def _run(argv: list, **kw) -> None:
    subprocess.run(argv, check=True, **kw)


def _find_conda() -> str:
    # conda before mamba: mamba 2 lists an explicit environment without the
    # @EXPLICIT line (conda uses the libmamba solver anyway)
    conda = (os.getenv("CONDA") or shutil.which("conda") or shutil.which("mamba")
             or os.path.expanduser("~/miniforge3/bin/conda"))
    if not os.access(conda, os.X_OK):
        raise SystemExit("error: conda not found: install Miniforge or set CONDA=/path/to/conda")
    return conda


LOCK_SPEC = "# solved from env.yaml: "


def _explicit(listing: str) -> str:
    """An explicit environment file of a listing: @EXPLICIT and the package
    URLs (mamba's listing has no @EXPLICIT, and a line naming the environment)."""
    urls = [line.strip() for line in listing.splitlines()
            if line.strip().startswith(("https://", "http://", "file://"))]
    return "@EXPLICIT\n" + "".join(url + "\n" for url in urls)


def _lock_spec(lock: str):
    """The lists of env.yaml a lock written by setup was solved from (None
    for a lock written otherwise, which is taken as it is)."""
    with open(lock) as f:
        for line in f:
            if line.startswith(LOCK_SPEC):
                return line[len(LOCK_SPEC):].strip()
            if not line.startswith("#"):
                break
    return None


def _conda_env(conda: str, prefix: str, lock: str, packages: list, what: str, channels: list) -> None:
    """A conda environment: exactly the packages of lock when it exists, else
    solved from packages, whose solution is then written to lock. A lock solved
    from other lists than env.yaml's now is solved again, and an environment
    made from other lists is made again."""
    wanted = json.dumps({"packages": packages, "channels": channels}, sort_keys=True)
    done = os.path.join(prefix, ".bench-created")
    if os.path.isfile(done) and open(done).read() == wanted:
        return
    if os.path.isfile(lock) and _lock_spec(lock) not in (None, wanted):
        print(f"{os.path.basename(lock)} was solved from other lists of env.yaml: solving them again")
        os.remove(lock)
    shutil.rmtree(prefix, ignore_errors=True)      # what a failed setup left, or an environment of other lists
    _step(f"{what} environment: {prefix}")
    if os.path.isfile(lock):
        explicit = prefix.rstrip("/") + ".explicit.txt"
        with open(lock) as f, open(explicit, "w") as out:
            out.write(_explicit(f.read()))
        try:
            _run([conda, "create", "-y", "-q", "-p", prefix, "--file", explicit])
        finally:
            os.remove(explicit)
    else:
        _run([conda, "create", "-y", "-q", "-p", prefix, "--override-channels",
              *[a for c in channels for a in ("-c", c)], *packages])
        listing = subprocess.run([conda, "list", "-p", prefix, "--explicit", "--md5"], check=True,
                                 capture_output=True, text=True).stdout
        with open(lock, "w") as f:
            f.write(f"# the packages of the {what} environment, written by make setup-env from env.yaml;\n"
                    "# later setups install exactly these (delete this file to solve env.yaml again)\n"
                    f"{LOCK_SPEC}{wanted}\n" + _explicit(listing))
        shown = os.path.relpath(lock, ROOT) if lock.startswith(ROOT + os.sep) else lock
        print(f"wrote {shown}: commit it with env.yaml")
    with open(done, "w") as f:
        f.write(wanted)


def _java_home(d: str):
    for javac in (os.path.join(d, "tools", "bin", "javac"), os.path.join(d, "build", "bin", "javac")):
        if os.path.exists(javac):
            return os.path.dirname(os.path.dirname(os.path.realpath(javac)))
    return None


def _tool_env(d: str, variables: dict = None) -> dict:
    """The environment's tools first in PATH, its C++ runtime in LD_LIBRARY_PATH,
    and the variables of env.yaml's env ($BENCH_ENV_DIR expanded)."""
    path = os.pathsep.join(p for p in (os.path.join(d, "bin"), os.path.join(d, "build", "bin"),
                                       os.path.join(d, "tools", "bin")) if os.path.isdir(p))
    env = dict(os.environ, PATH=path + os.pathsep + os.environ.get("PATH", ""),
               LD_LIBRARY_PATH=os.path.join(d, "runtime-lib"))
    if _java_home(d):
        env["JAVA_HOME"] = _java_home(d)
    env["BENCH_ENV_DIR"] = d
    env.update({k: v.replace("${BENCH_ENV_DIR}", d).replace("$BENCH_ENV_DIR", d)
                for k, v in (variables or {}).items()})
    return env


def _download(url: str, path: str) -> None:
    if not os.path.isfile(path):
        print(f"downloading {url}", flush=True)
        urllib.request.urlretrieve(url, path + ".part")
        os.replace(path + ".part", path)


def _bazel(version: str, bootstrap, d: str, binary) -> None:
    """Bazel <version> in the environment's bin/, from the shared copy in
    BENCH_HOME/bazel/<version>, which is compiled from its sources once."""
    target = os.path.join(d, "bin", f"bazel-{version}")
    if os.path.isfile(target):
        return
    shared_dir = os.path.join(bench_home(), "bazel", version)
    shared = os.path.join(shared_dir, "bazel")
    os.makedirs(shared_dir, exist_ok=True)
    if binary and not os.path.isfile(shared):
        _step(f"Bazel {version} from {binary}")
        shutil.copyfile(binary, shared + ".tmp")
        os.replace(shared + ".tmp", shared)
    if not os.path.isfile(shared):
        if not _java_home(d):
            raise SystemExit("error: compiling Bazel needs Java: add openjdk to tools (or conda) in env.yaml")
        # Java, zip and unzip from the tools environment, python3 (Bazel runs
        # Python tools) from the build environment, the C/C++ compiler from the host
        env = dict(os.environ, JAVA_HOME=_java_home(d),
                   PATH=os.pathsep.join([os.path.join(d, "tools", "bin"), os.path.join(d, "build", "bin"),
                                         os.environ.get("PATH", "")]),
                   EXTRA_BAZEL_ARGS="--host_javabase=@local_jdk//:jdk --local_ram_resources=HOST_RAM*.5")
        src = os.path.join(bench_home(), "bazel", "src")
        os.makedirs(src, exist_ok=True)

        def compile_from_sources(v: str) -> str:
            tree = os.path.join(src, f"bazel-{v}")
            built = os.path.join(tree, "output", "bazel")
            if not os.path.isfile(built):
                _step(f"Bazel {v} from its sources")
                zip_file = os.path.join(src, f"bazel-{v}-dist.zip")
                _download(f"https://github.com/bazelbuild/bazel/releases/download/{v}/bazel-{v}-dist.zip", zip_file)
                shutil.rmtree(tree, ignore_errors=True)
                os.makedirs(tree)
                _run(["unzip", "-q", zip_file], cwd=tree, env=env)
                _run(["bash", "./compile.sh"], cwd=tree, env=env)
            return built

        if bootstrap:
            first = compile_from_sources(bootstrap)
            _step(f"Bazel {version}, built with {bootstrap}")
            tree = os.path.join(src, f"bazel-{version}")
            zip_file = os.path.join(src, f"bazel-{version}-dist.zip")
            _download(f"https://github.com/bazelbuild/bazel/releases/download/{version}/bazel-{version}-dist.zip",
                      zip_file)
            shutil.rmtree(tree, ignore_errors=True)
            os.makedirs(tree)
            _run(["unzip", "-q", zip_file], cwd=tree, env=env)
            out_root = os.path.join(src, "bazel-out")
            _run([first, f"--output_user_root={out_root}", "build", "--local_ram_resources=HOST_RAM*.5",
                  f"--embed_label={version}", "//src:bazel_nojdk"], cwd=tree, env=env)
            shutil.copyfile(os.path.join(tree, "bazel-bin", "src", "bazel_nojdk"), shared + ".tmp")
            subprocess.run([first, f"--output_user_root={out_root}", "shutdown"], cwd=tree, env=env)
        else:
            shutil.copyfile(compile_from_sources(version), shared + ".tmp")
        os.replace(shared + ".tmp", shared)
        # the sources and build trees take several GB (Bazel leaves them read-only)
        subprocess.run(["chmod", "-R", "u+w", src], capture_output=True)
        shutil.rmtree(src, ignore_errors=True)
    os.chmod(shared, 0o755)
    shutil.copyfile(shared, target + ".tmp")     # a copy: containers see only the environment
    os.chmod(target + ".tmp", 0o755)
    os.replace(target + ".tmp", target)


def _norm(name: str) -> str:
    return re.split(r"[=<>!~ \[;]", name, 1)[0].strip().lower().replace("_", "-")


def _wheel_files(d: str, names: list) -> list:
    wheels = os.path.join(d, "wheels")
    found = []
    for name in names:
        match = [w for w in sorted(os.listdir(wheels)) if w.endswith(".whl")
                 and _norm(w.split("-", 1)[0]) == _norm(name)]
        if not match:
            raise SystemExit(f"error: no wheel of {name} in {wheels} (is it in wheels?)")
        found.append(os.path.join(wheels, match[-1]))
    return found


def _built_wheel(directory: str, spec: str):
    """The wheel of spec (name==version, or name) in directory, or None."""
    name, _, version = spec.partition("==")
    for f in sorted(os.listdir(directory)) if os.path.isdir(directory) else []:
        parts = f.split("-")
        if f.endswith(".whl") and _norm(parts[0]) == _norm(name) and (not version or parts[1] == version):
            return os.path.join(directory, f)
    return None


def _error_lines(log: str, limit: int = 12) -> list:
    """The first compiler and build errors of a log, without repeats."""
    seen, lines = set(), []
    with open(log, errors="replace") as f:
        for line in f:
            line = line.strip()
            if re.search(r"\berror\b|\bfailed\b|\bfatal\b", line, re.IGNORECASE) \
                    and not line.startswith(("note:", "Traceback", "File ")) and line not in seen:
                seen.add(line)
                lines.append(line[:300])
                if len(lines) == limit:
                    break
    return lines


def _pip(d: str, python: str, packages: list, wheels: list, marker: str, variables: dict = None) -> None:
    """pip packages into an environment: names among wheels from the built
    wheels; marker remembers the list installed."""
    wanted = "\n".join(packages)
    try:
        with open(marker) as f:
            if f.read() == wanted:
                return
    except OSError:
        pass
    if not packages:
        return
    built = {_norm(w) for w in wheels}
    local = [p for p in packages if _norm(p) in built]
    rest = [p for p in packages if _norm(p) not in built]
    env = _tool_env(d, variables)
    if local:
        _run([python, "-m", "pip", "install", "-q", "--no-deps", *_wheel_files(d, local)], env=env)
    if rest:
        _run([python, "-m", "pip", "install", "-q", *rest], env=env)
    with open(marker, "w") as f:
        f.write(wanted)


def _listing(conda: str, prefix: str) -> dict:
    if not os.path.isdir(prefix):
        return {}
    out = subprocess.run([conda, "list", "-p", prefix, "--json"], capture_output=True, text=True, check=True)
    return {p["name"]: p["version"] for p in json.loads(out.stdout)}


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def setup(name: str, bazel_binary: str = None, wheels_from: str = None) -> str:
    """Make environment `name` from envs/<name>/env.yaml in BENCH_HOME/envs/<name>."""
    spec, here, d = load(name), os.path.join(ENVS_DIR, name), env_dir(name)
    conda = _find_conda()
    for sub in ("bin", "runtime-lib", "wheels"):
        os.makedirs(os.path.join(d, sub), exist_ok=True)
    if os.path.exists(os.path.join(d, ".complete")):
        os.remove(os.path.join(d, ".complete"))       # until this setup ends

    if spec["conda"]:
        _conda_env(conda, os.path.join(d, "build"), os.path.join(here, "build.lock"), spec["conda"], "build",
                   spec["channels"])
    if spec["tools"]:
        _conda_env(conda, os.path.join(d, "tools"), os.path.join(here, "tools.lock"), spec["tools"], "tools",
                   spec["channels"])
    # the C++ runtime of the conda compilers, for the tools and wheels built
    # with them (a host's can be older), and the compiler names of rules_python
    for lib in ("libstdc++.so.6", "libgcc_s.so.1"):
        if os.path.exists(os.path.join(d, "build", "lib", lib)):
            link = os.path.join(d, "runtime-lib", lib)
            if os.path.lexists(link):
                os.remove(link)
            os.symlink(os.path.join(d, "build", "lib", lib), link)
    triplet = TRIPLETS.get(platform.machine())
    if triplet:
        for compiler, alias in (("clang", "gcc"), ("clang++", "g++")):
            if os.path.exists(os.path.join(d, "build", "bin", compiler)):
                link = os.path.join(d, "bin", f"{triplet}-{alias}")
                if os.path.lexists(link):
                    os.remove(link)
                os.symlink(os.path.join(d, "build", "bin", compiler), link)

    if spec.get("bazel"):
        version = str(spec["bazel"])
        bootstrap = spec.get("bazel_bootstrap", BAZEL_BOOTSTRAP.get(version))
        _bazel(version, str(bootstrap) if bootstrap else None, d, bazel_binary or os.getenv("BAZEL_BINARY"))

    wheels_dir, wheels_from = os.path.join(d, "wheels"), wheels_from or os.getenv("WHEELS_FROM")
    # one wheel at a time, each with its log: a wheel that fails names its
    # errors, and the next setup builds only the wheels still missing
    missing = [w for w in spec["wheels"] if not _built_wheel(wheels_dir, w)]
    failed = []
    env = _tool_env(d, spec["env"])
    if os.path.exists(os.path.join(d, "build", "bin", "clang")):
        env.update(CC="clang", CXX="clang++")
    for w in missing:
        if wheels_from:
            _step(f"wheel {w} from {wheels_from}")
            found = _built_wheel(wheels_from, w)
            if not found:
                raise SystemExit(f"error: no wheel {w} in {wheels_from}")
            shutil.copy2(found, wheels_dir)
            continue
        _step(f"wheel {w}")
        log = os.path.join(d, "logs", f"wheel-{_norm(w)}.log")
        os.makedirs(os.path.dirname(log), exist_ok=True)
        with open(log, "w") as out:
            code = subprocess.run([os.path.join(d, "build", "bin", "python"), "-m", "pip", "wheel", "--no-deps",
                                   "-w", wheels_dir, w], env=env, stdout=out, stderr=subprocess.STDOUT).returncode
        if code:
            failed.append(w)
            print(f"failed (status {code}), log {log}; its first errors:")
            for line in _error_lines(log):
                print(f"  {line}")
        else:
            print(f"built: {os.path.basename(_built_wheel(wheels_dir, w) or w)}")
    if failed:
        raise SystemExit(f"error: wheels that did not build: {', '.join(failed)}. Add what they need to conda "
                         "(or remove them from wheels) and run make setup-env again: the rest is kept")

    _pip(d, os.path.join(d, "build", "bin", "python"), spec["build_pip"], spec["wheels"],
         os.path.join(d, "build", ".bench-pip"), spec["env"])
    if spec["conda"]:
        # the test environment: the build's packages, and what the acceptance test imports
        _conda_env(conda, os.path.join(d, "test"), os.path.join(here, "build.lock"), spec["conda"], "test",
                   spec["channels"])
        _pip(d, os.path.join(d, "test", "bin", "python"), spec["test_pip"], spec["wheels"],
             os.path.join(d, "test", ".bench-pip"), spec["env"])

    # the variables of env, for env.sh, and the commands of setup, run once
    with open(os.path.join(d, "exports.sh"), "w") as f:
        f.write("# written by make setup-env from env.yaml (env)\n")
        for key, value in spec["env"].items():
            escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("`", "\\`")
            f.write(f'export {key}="{escaped}"\n')
    marker, wanted = os.path.join(d, ".bench-setup"), "\n".join(spec["setup"])
    done = open(marker).read() if os.path.isfile(marker) else None
    if spec["setup"] and done != wanted:
        env = _tool_env(d, spec["env"])
        for command in spec["setup"]:
            _step(f"setup: {command}")
            _run(["bash", "-euo", "pipefail", "-c", command], cwd=d, env=env)
    with open(marker, "w") as f:
        f.write(wanted)

    _step("env.json")
    info = {"name": name, "spec": spec,
            "build": _listing(conda, os.path.join(d, "build")), "tools": _listing(conda, os.path.join(d, "tools")),
            "test": _listing(conda, os.path.join(d, "test")),
            "wheels": {w: _sha256(os.path.join(wheels_dir, w)) for w in sorted(os.listdir(wheels_dir))
                       if w.endswith(".whl")}}
    if spec.get("bazel"):
        info["bazel"] = {"version": str(spec["bazel"]),
                         "sha256": _sha256(os.path.join(d, "bin", f"bazel-{spec['bazel']}"))}
    info["id"] = hashlib.sha256(json.dumps(info, sort_keys=True).encode()).hexdigest()[:12]
    with open(os.path.join(d, "env.json"), "w") as f:
        json.dump(info, f, indent=1)
    open(os.path.join(d, ".complete"), "w").close()
    print(f"environment {name} {info['id']}: {len(info['build'])} build packages, {len(info['test'])} test "
          f"packages, {len(info['wheels'])} wheels\nready: {d}", flush=True)
    return d
