import re

KEY_LINE = re.compile(
    r"error:|fatal error|\bFAILED\b|undefined reference|No such file or directory"
    r"|malformed patch|Bad exit status|make(\[\d+\])?: \*\*\*|\bKilled\b"
    r"|Segmentation fault|cannot find -l|nothing provides|have choice for",
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
    r"libgpg-error|-Werror|-Wno-error|error\.[ch]\b|errors?\.(c|h|o|go)\b"
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


def error_excerpt(log_text: str, max_key_lines: int = 15, tail_lines: int = 5) -> str:
    """Pick the lines of an OBS build log that explain the failure."""
    lines = [l.rstrip() for l in log_text.splitlines()]
    start = next((i for i, l in enumerate(lines) if BUILD_START.search(l)), 0)
    lines = lines[start:]

    key, seen = [], set()

    def add(line):
        if _text(line) and _text(line) not in seen:
            seen.add(_text(line))
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
        if PATCH_ERROR.search(line):
            for context in (patch_header, patching_file):
                if context:
                    add(context)
            add(line)
        elif KEY_LINE.search(line):
            add(line)
    key = key[-max_key_lines:]
    tail = [l for l in lines[-tail_lines:]
            if _text(l) and _text(l) not in seen and not NOISE.search(l)]
    return "\n".join(key + (["..."] if key and tail else []) + tail)
