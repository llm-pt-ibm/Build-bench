import re

KEY_LINE = re.compile(
    r"error:|fatal error|\bFAILED\b|undefined reference|No such file or directory"
    r"|malformed patch|Bad exit status|make(\[\d+\])?: \*\*\*|\bKilled\b"
    r"|Segmentation fault|cannot find -l|nothing provides|have choice for"
    # Bazel/Starlark: "Error in fail: ..." and the "... FAIL: <message>" lines
    r"|Error in \w+:|\bFAIL:"
    # glog/absl fatal messages (F1014 12:00:00.000 123 file.cc:42] ...) and
    # failed checks, e.g. a crash when a built program runs in a test
    r"|^[FE]\d{4} \d\d:\d\d:\d\d\.\d+ +\d+ \S+:\d+\]|Check failed|Traceback \(most recent call last\)|\bAborted\b",
    re.IGNORECASE,
)
# Messages of patch(1); they explain why a hunk failed, so they are kept with
# the "Patch #N (file):" header of the patch being applied.
PATCH_ERROR = re.compile(
    r"unexpectedly ends in middle of line|malformed patch|Only garbage was found"
    r"|can't find file to patch|Reversed \(or previously applied\) patch"
    r"|hunks? FAILED|Hunk #\d+ FAILED",
    re.IGNORECASE,
)
PATCH_HEADER = re.compile(r"^(\[\s*\d+s\]\s*)?Patch #\d+ \(")
PATCHING_FILE = re.compile(r"^(\[\s*\d+s\]\s*)?patching file ")
NOISE = re.compile(
    r"libgpg-error|-Werror|-Wno-error|error\.[ch]\b|errors?\.(c|h|o|go)\b|inlining failed"
    r"|scriptlet failed|VM INTERACTION|sysrq:|^(\[\s*\d+s\]\s*)?\S+ failed \"build "
)
# Start of the package build; lines before it come from installing the build
# environment and are not related to the package.
BUILD_START = re.compile(r"----- building |exec rpmbuild |Executing\(%")
# Timestamp and the "error: " prefix, so the summary that rpm repeats under
# "RPM build errors:" is not shown twice.
PREFIX = re.compile(r"^(\[\s*\d+s\]\s*)?(error:\s*)?")


def _text(line: str) -> str:
    return PREFIX.sub("", line.strip()).strip()


# A failed build action as Bazel reports it, one line per source file; the
# compiler diagnostics above it explain the failure, so these lines are
# collapsed to one per target
ACTION_FAILED = re.compile(r"^ERROR: .*: (?:Compiling|Linking|Generating|Executing|Action) .* failed[:.]")
ACTION_TARGET = re.compile(r"\(from target (\S+?)\)\s*$")
MAX_ACTION_LINES = 5
LAST_LINES_KEPT = 3


def error_excerpt(log_text: str, max_key_lines: int = 15, tail_lines: int = 5) -> str:
    """Pick the lines of a build log that explain the failure: compiler and
    build-tool error messages (each once, with its count when repeated),
    failed build actions collapsed per target, and the end of the log."""
    lines = [l.rstrip() for l in log_text.splitlines()]
    start = next((i for i, l in enumerate(lines) if BUILD_START.search(l)), 0)
    lines = lines[start:]

    key, seen, count = [], set(), {}
    actions = {}  # target -> [first line, number of failed actions]

    def add(line):
        text = _text(line)
        if not text:
            return
        count[text] = count.get(text, 0) + 1
        if text not in seen:
            seen.add(text)
            key.append(line)

    patch_header = patching_file = None
    for line in lines:
        if PATCH_HEADER.search(line):
            patch_header, patching_file = line, None
            continue
        if PATCHING_FILE.search(line):
            patching_file = line
            continue
        if NOISE.search(line):
            continue
        if ACTION_FAILED.search(line):
            m = ACTION_TARGET.search(line)
            group = actions.setdefault(m.group(1) if m else line, [line, 0])
            group[1] += 1
            seen.add(_text(line))
        elif PATCH_ERROR.search(line):
            for context in (patch_header, patching_file):
                if context:
                    add(context)
            add(line)
        elif KEY_LINE.search(line):
            add(line)

    action_lines = [line if n == 1 else f"{line} [and {n - 1} more failed actions of this target]"
                    for line, n in list(actions.values())[:MAX_ACTION_LINES]]
    if len(actions) > MAX_ACTION_LINES:
        action_lines.append(f"[{len(actions) - MAX_ACTION_LINES} more targets with failed actions]")
    budget = max(max_key_lines - len(action_lines), LAST_LINES_KEPT + 1)
    if len(key) > budget:
        # keep the most repeated messages (an error in a header shows up once
        # per file that includes it), the first ones (usually the cause) and
        # the last ones (the outcome), in log order
        middle = key[:-LAST_LINES_KEPT]
        room = budget - LAST_LINES_KEPT
        frequent = sorted(range(len(middle)), key=lambda i: -count[_text(middle[i])])[:room // 2]
        chosen = sorted(frequent + [i for i in range(len(middle)) if i not in frequent][:room - len(frequent)])
        key = [middle[i] for i in chosen] + ["..."] + key[-LAST_LINES_KEPT:]
    shown = [l if count.get(_text(l), 1) == 1 else f"{l} [x{count[_text(l)]}]" for l in key]
    tail = [l for l in (lines[-tail_lines:] if tail_lines > 0 else [])
            if _text(l) and _text(l) not in seen and not NOISE.search(l)]
    body = shown + action_lines
    return "\n".join(body + (["..."] if body and tail else []) + tail)


def _normalize(line: str) -> str:
    """A key line without what changes between equivalent builds: timestamps,
    absolute paths, hashes and numbers."""
    line = _text(line)
    line = re.sub(r"\S*/external/", "<ext>/", line)
    line = re.sub(r"\S*temp_workspace/[^/\s]+/", "", line)
    line = re.sub(r"\b[0-9a-f]{12,}\b", "<hash>", line)
    return re.sub(r"\d+", "#", line).strip()


def key_lines(log_text: str) -> list:
    """The error lines of a build log, normalized, in order of appearance."""
    lines = [l.rstrip() for l in log_text.splitlines()]
    start = next((i for i, l in enumerate(lines) if BUILD_START.search(l)), 0)
    out = []
    for line in lines[start:]:
        if NOISE.search(line) or not (PATCH_ERROR.search(line) or KEY_LINE.search(line)):
            continue
        norm = _normalize(line)
        if norm and norm not in out:
            out.append(norm)
    return out


def same_failure(original_log: str, new_log: str) -> bool:
    """Whether a build failed for the same root cause as the original failure:
    the first error of the new log is one of the errors of the original."""
    new, original = key_lines(new_log), key_lines(original_log)
    if not new or not original:
        return not new and not original
    return new[0] in original
