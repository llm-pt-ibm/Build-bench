import re

KEY_LINE = re.compile(
    r"error:|fatal error|\bFAILED\b|undefined reference|No such file or directory"
    r"|malformed patch|Bad exit status|make(\[\d+\])?: \*\*\*|\bKilled\b"
    r"|Segmentation fault|cannot find -l|nothing provides|have choice for",
    re.IGNORECASE,
)
NOISE = re.compile(r"libgpg-error|-Werror|-Wno-error|error\.[ch]\b|errors?\.(c|h|o|go)\b")


def error_excerpt(log_text: str, max_key_lines: int = 15, tail_lines: int = 5) -> str:
    """Pick the lines of an OBS build log that explain the failure."""
    lines = [l.rstrip() for l in log_text.splitlines()]
    key = []
    for line in lines:
        if KEY_LINE.search(line) and not NOISE.search(line) and line not in key:
            key.append(line)
    key = key[-max_key_lines:]
    tail = [l for l in lines[-tail_lines:] if l.strip() and l not in key]
    return "\n".join(key + (["..."] if key and tail else []) + tail)
