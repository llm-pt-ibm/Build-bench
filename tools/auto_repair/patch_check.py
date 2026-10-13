import re

HUNK_HEADER = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
GIT_EXTENDED = re.compile(r"^(rename|copy) (from|to) |^(new|deleted) file mode |^(old|new) mode |"
                          r"^similarity index |^GIT binary patch|^Binary files ", re.MULTILINE)


def check_patch_format(text: str) -> list:
    """Return the structural problems that make `patch` reject a unified diff.

    Each hunk header declares how many old (-) and new (+) lines its body has;
    rpm applies patches with --fuzz=0, so a count that does not match the body
    is fatal.
    """
    lines = text.split("\n")
    n = len(lines)
    problems = []
    hunks = 0
    i = 0
    while i < n:
        m = HUNK_HEADER.match(lines[i])
        if not m:
            i += 1
            continue
        hunks += 1
        header_line = i + 1
        old_decl = int(m.group(2) if m.group(2) is not None else 1)
        new_decl = int(m.group(4) if m.group(4) is not None else 1)
        old_seen = new_seen = 0
        i += 1
        while i < n and (old_seen < old_decl or new_seen < new_decl):
            line = lines[i]
            if line.startswith("\\"):
                pass
            elif line.startswith("-"):
                old_seen += 1
            elif line.startswith("+"):
                new_seen += 1
            elif line.startswith(" ") or (line == "" and i < n - 1):
                old_seen += 1
                new_seen += 1
            else:
                break
            i += 1
        at_eof = all(l == "" for l in lines[i:])
        missing_context = old_decl - old_seen == new_decl - new_seen > 0
        if at_eof and missing_context:
            # GNU patch accepts a last hunk cut short by trailing context lines
            continue
        if old_seen != old_decl or new_seen != new_decl:
            problems.append(
                f"hunk at line {header_line} declares -{old_decl}/+{new_decl} lines "
                f"but its body has -{old_seen}/+{new_seen}")
            continue
        if i < n:
            nxt = lines[i]
            signature = nxt == "-- "  # git format-patch trailer
            # a change line past the declared count is silently dropped by
            # patch; extra context lines are ignored and harmless
            if nxt[:1] in ("+", "-") and not signature and not nxt.startswith(("+++ ", "--- ")):
                problems.append(
                    f"hunk at line {header_line} has more lines than its header "
                    f"declares (-{old_decl}/+{new_decl}); extra line {i + 1}: {nxt[:80]!r}")
    # empty patches and git patches that only rename, copy or change modes are valid
    git_only = GIT_EXTENDED.search(text)
    if hunks == 0 and text.strip() and not git_only:
        problems.append("no hunk header (@@ -a,b +c,d @@) found")
    return problems
