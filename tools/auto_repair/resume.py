"""Continuing a run: the changes the earlier attempts made to a package,
relative to the original package, as unified diffs for the model."""
import difflib
import os

NOT_SOURCES = {"log_failed.txt", "log_failed_original.txt", "manifest.json", "extracted"}
FILE_MAX_CHARS = 3000
TOTAL_MAX_CHARS = 20000


def _files(root: str) -> dict:
    out = {}
    for dirpath, dirs, files in os.walk(root):
        rel = os.path.relpath(dirpath, root)
        if rel == ".":
            dirs[:] = [d for d in dirs if d not in NOT_SOURCES and not d.startswith(".")]
            files = [f for f in files if f not in NOT_SOURCES and not f.startswith(".")]
        for name in files:
            path = os.path.join(dirpath, name)
            # symlinks are followed: copying the package turns them into files
            if os.path.isfile(path):
                st = os.stat(path)
                out[os.path.normpath(os.path.join(rel, name))] = (st.st_size, int(st.st_mtime))
    return out


def _read(path: str):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read().splitlines(keepends=True)
    except (OSError, UnicodeDecodeError):
        return None


def workspace_changes(original: str, work: str) -> str:
    """Unified diffs of the files that differ between the original package and
    the workspace (files with the same size and mtime are taken as unchanged)."""
    before, after = _files(original), _files(work)
    parts, total = [], 0
    for rel in sorted(set(before) | set(after)):
        if rel in before and rel in after and before[rel] == after[rel]:
            continue
        old = _read(os.path.join(original, rel)) if rel in before else []
        new = _read(os.path.join(work, rel)) if rel in after else []
        if old is None or new is None:
            text = f"File: {rel} (binary file changed)"
        elif old == new:
            continue
        else:
            diff = "".join(difflib.unified_diff(old, new, fromfile=f"a/{rel}" if rel in before else "/dev/null",
                                                tofile=f"b/{rel}" if rel in after else "/dev/null"))
            if len(diff) > FILE_MAX_CHARS:
                diff = diff[:FILE_MAX_CHARS] + "\n... [diff truncated]\n"
            text = f"File: {rel}\n```diff\n{diff}```"
        if total + len(text) > TOTAL_MAX_CHARS:
            parts.append("... [more changed files not shown]")
            break
        parts.append(text)
        total += len(text)
    return "\n\n".join(parts)
