"""Leak check: before a package runs, look for the answer in what the model can
read: a built copy of the package (an installed Python package, a wheel, a
conda package, an RPM) or a file of its reference fix (dataset/reference/<pkg>,
compared by content).

Checked: the case (copied into the workspace when a run starts), the
acceptance tests, the build environments and the runner, and, for build-recipe
cases, the paths run_command_tool's sandbox shows (script.experiment_paths,
except script.experiment_hide). Not checked: the build cache, which is cleared
when a run starts and on a continued run holds the model's own builds, and
what build.sh can reach: it runs outside the sandbox, with the whole host.

Found in runs 28 and 28c: a reference build in the stage root (the file tools
could read all of it) and the team's jaxlib installed in two conda
environments of the build host."""
import hashlib
import os
import re

from tools.auto_repair.case_type import case_type

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
PACKAGE_FILES = (".whl", ".conda", ".rpm")
DIST_INFO = re.compile(r"^(.+?)-\d[^-]*\.(dist-info|egg-info)$")
MAX_FINDINGS = 20


def _names(package: str) -> set:
    name = package.lower()
    return {name, name.replace("-", "_"), name.replace("_", "-")}


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _reference_files(package: str) -> dict:
    """size -> {sha256: reference path} of the package's reference fix."""
    refs = {}
    for root, _, files in os.walk(os.path.join(ROOT, "dataset", "reference", package)):
        for name in files:
            path = os.path.join(root, name)
            try:
                refs.setdefault(os.path.getsize(path), {})[_sha256(path)] = os.path.relpath(path, ROOT)
            except OSError:
                pass
    return refs


def _is_built_copy(path: str, names: set, is_dir: bool) -> bool:
    base = os.path.basename(path).lower()
    parent = os.path.basename(os.path.dirname(path)).lower()
    if is_dir:
        if parent not in ("site-packages", "dist-packages"):
            return False
        m = DIST_INFO.match(base)
        return base in names or bool(m and m.group(1) in names)
    starts = any(base.startswith(n + "-") or base.startswith(n + "_") for n in names)
    if base.endswith(PACKAGE_FILES):
        return starts or (base.endswith(".rpm") and any(n in base for n in names))
    # conda's older package format, in a package cache
    return base.endswith(".tar.bz2") and starts and parent == "pkgs"


def readable_roots(cfg: dict, package: str, case_dir: str) -> tuple:
    """(directories to check, hidden directories inside them)."""
    roots = [case_dir, os.path.join(ROOT, "acceptance"), os.path.join(ROOT, "envs"),
             os.path.join(ROOT, "scripts", "script_worker")]
    hidden = []
    if case_type(case_dir) == "recipe":
        script = cfg.get("script") or {}
        roots += [p for p in script.get("experiment_paths") or [] if os.path.exists(p)]
        hidden = [os.path.realpath(p) for p in script.get("experiment_hide") or [] if os.path.exists(p)]
    return [os.path.realpath(r) for r in roots if os.path.isdir(r)], hidden


def leak_report(cfg: dict, package: str, case_dir: str) -> list:
    """What the model could read that gives the answer away, one line each."""
    names, refs = _names(package), _reference_files(package)
    roots, hidden = readable_roots(cfg, package, case_dir)
    found, seen = [], set()

    def report(reason, path):
        if path not in seen and len(found) < MAX_FINDINGS:
            seen.add(path)
            found.append(f"{reason}: {path}")

    def is_hidden(path):
        real = os.path.realpath(path)
        return any(real == h or real.startswith(h + os.sep) for h in hidden)

    for top in roots:
        for root, dirs, files in os.walk(top):
            for d in list(dirs):
                if is_hidden(os.path.join(root, d)):
                    dirs.remove(d)
                elif _is_built_copy(os.path.join(root, d), names, True):
                    report(f"installed copy of {package}", os.path.join(root, d))
                    dirs.remove(d)
            for name in files:
                path = os.path.join(root, name)
                if _is_built_copy(path, names, False):
                    report(f"built copy of {package}", path)
                    continue
                try:
                    candidates = refs.get(os.path.getsize(path)) if refs else None
                    if candidates:
                        ref = candidates.get(_sha256(path))
                        if ref:
                            report(f"file of the reference fix ({ref})", path)
                except OSError:
                    pass
    return found
