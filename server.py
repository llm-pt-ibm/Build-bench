import os
import json
import shutil
import subprocess
import difflib
import time
from mcp.server.fastmcp import FastMCP
from datetime import datetime
from tools.auto_repair.get_repo_structure import get_project_structure_from_local
from tools.auto_repair.check_build_res import check_main
from tools.auto_repair.upload_files import main_upload
from tools.auto_repair.local_build import local_upload, local_check
from tools.auto_repair.script_build import script_upload, script_check
from tools.auto_repair.case_type import case_type
from tools.auto_repair.obs_config import load_obs_config
from tools.auto_repair.patch_check import check_patch_format
import tarfile
import zipfile

mcp = FastMCP("auto_repair_server")

# Server-side state storage
server_state = {
    "modification_history": {},  # {package_name: [{file_path, diff, timestamp}, ...]}
    "tool_call_history": {},  # {package_name: [(tool_name, args_key), ...]}
    "tool_cache": {},  # {package_name: {call_key: result, ...}}
    "extractions": {},  # {package_dir: {"archive": path, "fingerprint": [...]}}
}

# Directory that holds the per-package working copies; file tools refuse paths
# outside it. The client passes it through the environment.
TEMP_ROOT = os.path.realpath(os.getenv("BENCH_TEMP_DIR", "temp_workspace"))
FILE_MAX_CHARS = 60000
# Some models (DeepSeek, Qwen3-Coder) cannot end a tool-call string argument
# with a newline: their tool-call format trims it. With "add", modify_file_tool
# restores the final newline of a new file or of a file that had one, so that
# patches are not rejected for it; "off" writes the content unchanged.
FINAL_NEWLINE = os.getenv("BENCH_FINAL_NEWLINE", "add").lower()


def _in_workspace(path) -> bool:
    real = os.path.realpath(str(path))
    return real == TEMP_ROOT or real.startswith(TEMP_ROOT + os.sep)


# Directories the model may read but not change (e.g. dependency sources a
# build downloaded into its cache), set by the client from the config.
READONLY_ROOTS = [os.path.realpath(d) for d in os.getenv("BENCH_READONLY_DIRS", "").split(os.pathsep) if d]


def _readable(path) -> bool:
    real = os.path.realpath(str(path))
    return _in_workspace(path) or any(real == r or real.startswith(r + os.sep) for r in READONLY_ROOTS)


def _unreadable(path) -> str:
    extra = f" or the read-only build directories ({', '.join(READONLY_ROOTS)})" if READONLY_ROOTS else ""
    return (f"Error: '{path}' is outside the package workspace ({os.path.relpath(TEMP_ROOT)}){extra}.")


def _outside(path) -> str:
    return (f"Error: '{path}' is outside the package workspace "
            f"({os.path.relpath(TEMP_ROOT)}); use paths inside the package directory.")


def _package_and_rel(file_path):
    rel = os.path.relpath(os.path.realpath(file_path), TEMP_ROOT)
    parts = rel.split(os.sep)
    return parts[0], os.sep.join(parts[1:]) or rel


def _fingerprint(directory):
    entries = []
    for root, _, files in os.walk(directory):
        for name in files:
            path = os.path.join(root, name)
            st = os.lstat(path)
            entries.append((os.path.relpath(path, directory), st.st_size, st.st_mtime_ns))
    return sorted(entries)


@mcp.tool()
def init_package_environment_tool(
    base_dir: str, package_name: str, temp_work_dir: str, result_dir: str) -> str:
    """
    Initializes the package's temporary working environment and copies the original files to a temporary directory.
    Args:
        base_dir: Base directory
        package_name: Package name
        temp_work_dir: Temporary working directory
        result_dir: Result storage directory
    Returns:
        JSON string containing the initialization result
    """
    try:
        package_temp_dir = os.path.join(temp_work_dir, package_name)
        server_state["modification_history"].pop(package_name, None)
        server_state["extractions"].pop(os.path.realpath(package_temp_dir), None)
        if os.path.exists(package_temp_dir):
            shutil.rmtree(package_temp_dir)
        os.makedirs(package_temp_dir, exist_ok=True)

        original_package_path = os.path.join(base_dir, package_name)
        if not os.path.exists(original_package_path):
            return json.dumps(
                {
                    "success": False,
                    "message": f"Original package path not found: {original_package_path}",
                }
            )

        # Copy the file to a temporary directory
        for item in os.listdir(original_package_path):
            src = os.path.join(original_package_path, item)
            dst = os.path.join(package_temp_dir, item)
            if os.path.isdir(src):
                shutil.copytree(src, dst, dirs_exist_ok=True)
            else:
                shutil.copy2(src, dst)

        # keep the original failure: log_failed.txt is replaced after each failed build
        original_log = os.path.join(package_temp_dir, "log_failed.txt")
        if os.path.exists(original_log):
            shutil.copy2(original_log, os.path.join(package_temp_dir, "log_failed_original.txt"))

        result_file = os.path.join(result_dir, f"{package_name}_result.txt")

        return json.dumps(
            {
                "success": True,
                "package_temp_dir": package_temp_dir,
                "package_path": package_temp_dir,
                "result_file": result_file,
                "message": f"Initialized package environment: {package_temp_dir}",
            }
        )
    except Exception as e:
        return json.dumps(
            {"success": False, "message": f"Initialization failed: {str(e)}"}
        )


@mcp.tool()
def track_file_modification_tool(
    package_name: str,
    file_path: str,
    package_path: str,
    old_content: str,
    new_content: str,) -> str:
    """
    Tracks file modification history and records differences.
    Args:
        package_name: Package name
        file_path: File path (relative path)
        package_path: Package path
        old_content: Content before modification
        new_content: Content after modification
    Returns:
        Tracking results
    """
    try:
        if package_name not in server_state["modification_history"]:
            server_state["modification_history"][package_name] = []

        old_lines = old_content.splitlines(keepends=True)
        new_lines = new_content.splitlines(keepends=True)

        # Calculate the difference
        diff = []
        for i, line in enumerate(
            difflib.unified_diff(old_lines, new_lines, lineterm="")
        ):
            if i < 3:
                continue
            if line.startswith("+"):
                diff.append(
                    {
                        "operation": "add",
                        "line_number": i - 2,
                        "content": line[1:].rstrip("\n"),
                    }
                )
            elif line.startswith("-"):
                diff.append(
                    {
                        "operation": "delete",
                        "line_number": i - 2,
                        "content": line[1:].rstrip("\n"),
                    }
                )
            elif line.startswith(" "):
                diff.append(
                    {
                        "operation": "keep",
                        "line_number": i - 2,
                        "content": line[1:].rstrip("\n"),
                    }
                )

        # Storage differences
        server_state["modification_history"][package_name].append(
            {
                "file_path": file_path,
                "diff": diff,
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
        )

        return f"Successfully tracked modification to {file_path}"
    except Exception as e:
        return f"Error tracking modification: {str(e)}"


@mcp.tool()
def parse_build_result_tool(result_content: str, package_name: str) -> str:
    """
    Parse the build results to determine success.
    Args:
        result_content: Build result content
        package_name: Package name
    Returns:
        JSON string containing the parsed results
    """
    try:
        status = result_content.split(": ", 1)[-1]
        success = status.startswith("Build succeeded!")
        return json.dumps({"success": success, "status": status})
    except Exception:
        return json.dumps({"success": False, "status": "Unknown (parse error)"})


DIFF_PROMPT_MAX_CHARS = 3000


@mcp.tool()
def update_prompt_with_history_tool(
    package_name: str, package_path: str, build_attempt: int, formatted_prompt: str) -> str:
    """
    Update prompt, including modification history.
    Args:
        package_name: Package name
        package_path: Package path
        build_attempt: Number of build attempts
        formatted_prompt: Formatted system prompt
    Returns:
        JSON string containing the updated message list
    """
    current_prompt = (
        f"Please analyze and repair package {package_name} in: {package_path}. "
    )
    current_prompt += "All modifications must be done in the temporary directory. "

    # Add historical modification records
    if build_attempt > 1:
        prev_modifications = server_state["modification_history"].get(package_name, [])
        if prev_modifications:
            current_prompt += "\n\nPrevious modifications:\n"
            for mod in prev_modifications:
                current_prompt += f"File: {mod['file_path']}\n"
                if "diff_text" in mod:
                    text = mod["diff_text"]
                    if len(text) > DIFF_PROMPT_MAX_CHARS:
                        text = text[:DIFF_PROMPT_MAX_CHARS] + "\n... [diff truncated]"
                    current_prompt += f"```diff\n{text}\n```\n\n"
                    continue
                current_prompt += "Changes:\n"
                for change in mod.get("diff", []):
                    op = change["operation"]
                    line = change["line_number"]
                    content = change["content"][:200]
                    current_prompt += f"- Line {line} ({op}): {content}\n"
                current_prompt += "\n"
        current_prompt += f"After {build_attempt - 1} attempts, build still failed. "
        current_prompt += (
            "Analyze previous modifications and failures, then provide new repair plan."
        )

    return json.dumps(
        {
            "messages": [
                {"role": "system", "content": formatted_prompt},
                {"role": "user", "content": current_prompt},
            ]
        }
    )


@mcp.tool()
def get_file_content_tool(file_path: str, start_line: int = 1, max_lines: int = 0) -> str:
    """
    Get file contents.
    Args:
        file_path: Path of the file inside the package directory
        start_line: First line to return (1-based, default 1)
        max_lines: Number of lines to return (default 0: until the end of the file)
    Returns:
        File contents. Very large files are shortened in the middle; read a
        specific part with start_line/max_lines.
    """
    if not _readable(file_path):
        return _unreadable(file_path)
    try:
        if not os.path.exists(file_path):
            return f"Error: File not found - {file_path}"
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
        if start_line > 1 or max_lines > 0:
            lines = text.splitlines(keepends=True)
            first = max(start_line, 1) - 1
            last = len(lines) if max_lines <= 0 else min(len(lines), first + max_lines)
            text = f"[lines {first + 1}-{last} of {len(lines)}]\n" + "".join(lines[first:last])
        if len(text) > FILE_MAX_CHARS:
            head = FILE_MAX_CHARS // 3
            tail = FILE_MAX_CHARS - head
            omitted = len(text) - head - tail
            text = (text[:head]
                    + f"\n... [{omitted} characters omitted; use start_line/max_lines to read them] ...\n"
                    + text[-tail:])
        return text
    except Exception as e:
        return f"Error reading file: {str(e)}"


@mcp.tool()
def check_repeat_tool_call(
    tool_name: str, args_key: str, max_repeat: int, package_name: str) -> str:
    """
    Check if the tool call is repeated
    Args:
        tool_name: Tool name
        args_key: Argument key
        max_repeat: Maximum repeat count
        package_name: Package name
    Returns:
        JSON string containing the check results
    """
    call_key = args_key
    if package_name not in server_state["tool_call_history"]:
        server_state["tool_call_history"][package_name] = []

    repeat_count = server_state["tool_call_history"][package_name].count(call_key)
    if repeat_count >= max_repeat:
        return json.dumps(
            {
                "allowed": False,
                "message": f"Tool call {tool_name} exceeded max repeat count ({max_repeat})",
            }
        )
    return json.dumps({"allowed": True, "message": "Tool call allowed"})


@mcp.tool()
def check_tool_cache(call_key: str, tool_name: str, package_name: str) -> str:
    """
    Check tool call result cache
    Args:
        call_key: Call key
        tool_name: Tool name
        package_name: Package name
    Returns:
        JSON string containing the cache check results
    """
    if package_name not in server_state["tool_cache"]:
        server_state["tool_cache"][package_name] = {}

    if call_key in server_state["tool_cache"][package_name]:
        return json.dumps(
            {"hit": True, "result": server_state["tool_cache"][package_name][call_key]}
        )
    return json.dumps({"hit": False, "result": ""})


@mcp.tool()
def cache_tool_result(call_key: str, result: str, package_name: str) -> str:
    """
    Cache tool call result
    Args:
        call_key: Call key
        result: Result content
        package_name: Package name
    Returns:
        Cache result
    """
    if package_name not in server_state["tool_cache"]:
        server_state["tool_cache"][package_name] = {}
    server_state["tool_cache"][package_name][call_key] = result
    return f"Successfully cached result for {call_key}"


@mcp.tool()
def reset_package_cache_tool(package_name: str) -> str:
    """
    Clear per-package caches for a new attempt.
    - Clears: tool_cache and tool_call_history
    - Keeps:  modification_history (so dynamic prompt can use it)
    """
    # initialize keys if missing
    server_state.setdefault("tool_cache", {})
    server_state.setdefault("tool_call_history", {})
    server_state.setdefault("modification_history", {})

    # clear cache + call history for this package
    if package_name in server_state["tool_cache"]:
        server_state["tool_cache"][package_name].clear()
    if package_name in server_state["tool_call_history"]:
        server_state["tool_call_history"][package_name].clear()

    return json.dumps(
        {
            "success": True,
            "message": f"Cleared tool_cache and tool_call_history for package '{package_name}'.",
        }
    )


@mcp.tool()
def record_tool_call_history(call_key: str, package_name: str) -> str:
    """
    Record tool call history
    Args:
        call_key: Call key
        package_name: Package name
    Returns:
        Record result
    """
    if package_name not in server_state["tool_call_history"]:
        server_state["tool_call_history"][package_name] = []
    server_state["tool_call_history"][package_name].append(call_key)
    return f"Recorded tool call history for {package_name}"


STRUCTURE_MAX_CHARS = 40000


@mcp.tool()
def get_structure_of_files(package_path, max_depth: int = 0) -> str:
    """
    Retrieve project structure diagram.
    Args:
        package_path (str): Package path.
        max_depth (int): Levels of subdirectories to list (default 0: all). Deeper
            directories are shown with their number of entries.
    """
    if not _readable(package_path):
        return _unreadable(package_path)
    text = json.dumps(get_project_structure_from_local(package_path, max_depth), indent=1)
    if len(text) > STRUCTURE_MAX_CHARS:
        text = (text[:STRUCTURE_MAX_CHARS]
                + f"\n... [truncated: {len(text)} characters in total. "
                "Use get_file_content_tool on the specific files you need.]")
    return text


# Files of the package root that belong to the framework, not to the package
FRAMEWORK_FILES = {"manifest.json", "log_failed_original.txt"}


def _write_file(file_path: str, new_content: str, action: str) -> str:
    """Write a file of the workspace, recording the change for the history and
    the diff log, and check patch files."""
    package_name, rel_path = _package_and_rel(file_path)
    if rel_path in FRAMEWORK_FILES:
        return f"Error: {rel_path} belongs to the benchmark framework and cannot be changed."
    created = not os.path.exists(file_path)
    parent = os.path.dirname(file_path) or "."
    if created and not os.path.isdir(parent):
        return f"Error: Directory does not exist - {parent}"

    diff_log_path = f"data/case_study/{package_name}_diff.log"

    old_lines = []
    if not created:
        with open(file_path, "r", encoding="utf-8") as f:
            old_lines = f.readlines()
    added_newline = (FINAL_NEWLINE == "add" and new_content and not new_content.endswith("\n")
                     and (created or not old_lines or old_lines[-1].endswith("\n")))
    if added_newline:
        new_content += "\n"
    new_lines = new_content.splitlines(keepends=True)

    diff = list(
        difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile="/dev/null" if created else f"{file_path} (old)",
            tofile=f"{file_path} (new)",
            lineterm="",
        )
    )

    if diff:
        # record the change for the next attempt's prompt
        server_state["modification_history"].setdefault(package_name, []).append(
            {
                "file_path": rel_path,
                "diff_text": "\n".join(line.rstrip("\n") for line in diff),
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
        )
        os.makedirs(os.path.dirname(diff_log_path), exist_ok=True)
        with open(diff_log_path, "a", encoding="utf-8") as log:
            log.write("\n" + "=" * 80 + "\n")
            log.write(f"Timestamp: {datetime.now()}\n")
            log.write(f"File: {file_path}\n")
            log.write(f"Diff lines: {len(diff)}\n\n")
            for line in diff:
                log.write(line + "\n")

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(new_content)

    message = f"Success: {'Created' if created else action} {file_path}\nPreview: {new_content[:100]}..."
    if added_newline:
        message += "\nNote: a final newline was added to the content."
    if file_path.endswith((".patch", ".diff")):
        # rpm applies patches with GNU patch; other build systems may use
        # stricter patchers (Bazel's ctx.patch, git apply)
        strict = case_type(os.path.join(TEMP_ROOT, package_name)) == "recipe"
        problems = check_patch_format(new_content, strict=strict)
        if problems:
            message += ("\nWarning: this patch is malformed and will be rejected when the "
                        "package is built (patches are applied with --fuzz=0): "
                        + "; ".join(problems))
    return message


@mcp.tool()
def modify_file_tool(file_path: str, new_content: str):
    """
    Replace the entire content of a file, or create a new file, inside the package directory.
    Args:
        file_path (str): File path to modify or create.
        new_content (str): Complete new content of the file.
    """
    if not _in_workspace(file_path):
        return _outside(file_path)
    try:
        return _write_file(file_path, new_content, "Replaced content of")
    except Exception as e:
        return f"Modify file failed: {str(e)}"


@mcp.tool()
def replace_in_file_tool(file_path: str, old_text: str, new_text: str, replace_all: bool = False):
    """
    Replace an exact piece of text in a file inside the package directory,
    without rewriting the whole file.
    Args:
        file_path (str): File to change.
        old_text (str): Text to replace, copied exactly from the file (including
            indentation). It must occur once, unless replace_all is true.
        new_text (str): Replacement text.
        replace_all (bool): Replace every occurrence (default false).
    """
    if not _in_workspace(file_path):
        return _outside(file_path)
    try:
        if not os.path.isfile(file_path):
            return f"Error: File not found - {file_path}"
        if not old_text:
            return "Error: old_text is empty"
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
        count = content.count(old_text)
        if count == 0:
            return f"Error: old_text was not found in {file_path}; read the file and copy the text exactly."
        if count > 1 and not replace_all:
            return (f"Error: old_text occurs {count} times in {file_path}; include more surrounding "
                    "lines to make it unique, or pass replace_all=true.")
        new_content = content.replace(old_text, new_text) if replace_all else content.replace(old_text, new_text, 1)
        message = _write_file(file_path, new_content, "Edited")
        return message.replace("Success: Edited", f"Success: Replaced {count if replace_all else 1} occurrence(s) in", 1)
    except Exception as e:
        return f"Replace failed: {str(e)}"


SEARCH_MAX_RESULTS = 200
SEARCH_LINE_CHARS = 300


@mcp.tool()
def search_files_tool(path: str, pattern: str, file_glob: str = "", max_results: int = 50):
    """
    Search the files under a directory for a regular expression (like grep -rn).
    Args:
        path (str): Directory or file to search, inside the package directory or a
            read-only build directory.
        pattern (str): Extended regular expression (grep -E syntax).
        file_glob (str): Only search files whose name matches this glob, e.g. "*.bzl".
        max_results (int): Maximum number of matching lines to return (default 50).
    Returns:
        Matching lines as path:line:text.
    """
    if not _readable(path):
        return _unreadable(path)
    if not os.path.exists(path):
        return f"Error: Path not found - {path}"
    limit = max(1, min(int(max_results or 50), SEARCH_MAX_RESULTS))
    cmd = ["grep", "-rInE", "--binary-files=without-match", "-e", pattern]
    if file_glob:
        cmd.append(f"--include={file_glob}")
    cmd.append(path)
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, errors="replace", timeout=300)
    except subprocess.TimeoutExpired:
        return "Error: search timed out; narrow the path or the pattern."
    if proc.returncode == 2 and not proc.stdout:
        return f"Error: {proc.stderr.strip()[:500]}"
    lines = proc.stdout.splitlines()
    if not lines:
        return "No matches."
    shown = [l if len(l) <= SEARCH_LINE_CHARS else l[:SEARCH_LINE_CHARS] + " ..." for l in lines[:limit]]
    more = f"\n... [{len(lines) - limit} more matches; narrow the search]" if len(lines) > limit else ""
    return "\n".join(shown) + more


SUPPORTED_FORMATS = {
    "tar.gz": {"extensions": [".tar.gz", ".tgz"], "mode": "r:gz"},
    "tar.xz": {"extensions": [".tar.xz", ".txz"], "mode": "r:xz"},
    "tar.bz2": {"extensions": [".tar.bz2", ".tbz"], "mode": "r:bz2"},
    "zip": {"extensions": [".zip"], "mode": "r"},
}
def get_archive_format(file_path: str) -> tuple:
    """Determine archive format"""
    for fmt, info in SUPPORTED_FORMATS.items():
        for ext in info["extensions"]:
            if file_path.lower().endswith(ext):
                return (fmt, info["mode"])
    return (None, None)


@mcp.tool()
def extract_archive_tool(package_path: str, force: bool = False):
    """
    Extract the package's source archive into <package_path>/extracted.
    Args:
        package_path: Package directory (or a specific archive inside it)
        force: Extract again even if extracted/ exists, discarding edits made inside it
    """
    if not _in_workspace(package_path):
        return _outside(package_path)
    try:
        archive_path = None
        package_dir = None
        archive_file = None

        if os.path.isfile(package_path):
            fmt, _ = get_archive_format(package_path)
            if fmt:
                archive_path = package_path
                package_dir = os.path.dirname(archive_path)
                archive_file = os.path.basename(archive_path)
            else:
                return f"Error: Unsupported archive format for '{package_path}'"

        elif os.path.isdir(package_path):
            for item in sorted(os.listdir(package_path)):
                item_path = os.path.join(package_path, item)
                if os.path.isfile(item_path) and get_archive_format(item_path)[0]:
                    archive_path = item_path
                    archive_file = item
                    package_dir = package_path
                    break
            if archive_path is None:
                return f"Error: No supported archive in '{package_path}'"

        else:
            return f"Error: Invalid path '{package_path}'"

        extract_dir = os.path.join(package_dir, "extracted")
        if os.path.exists(extract_dir) and not force:
            previous = server_state["extractions"].get(os.path.realpath(package_dir), {})
            source = os.path.basename(previous.get("archive", "")) or "an archive"
            return (f"Already extracted to {extract_dir} (from {source}); edits inside it are kept. "
                    "Pass force=true to discard them and extract again.")
        if os.path.exists(extract_dir):
            shutil.rmtree(extract_dir)
        os.makedirs(extract_dir, exist_ok=True)

        fmt, mode = get_archive_format(archive_path)
        if fmt in ["tar.gz", "tar.xz", "tar.bz2"]:
            with tarfile.open(archive_path, mode) as tar:
                try:
                    tar.extractall(extract_dir, filter="data")
                except TypeError:  # Python without extraction filters
                    tar.extractall(extract_dir)
        elif fmt == "zip":
            with zipfile.ZipFile(archive_path, "r") as zip_ref:
                root = os.path.realpath(extract_dir) + os.sep
                for name in zip_ref.namelist():
                    if not os.path.realpath(os.path.join(extract_dir, name)).startswith(root):
                        return f"Error: archive member '{name}' would be extracted outside {extract_dir}"
                zip_ref.extractall(extract_dir)

        server_state["extractions"][os.path.realpath(package_dir)] = {
            "archive": archive_path,
            "fingerprint": _fingerprint(extract_dir),
        }
        return f"Successfully extracted {archive_file} to {extract_dir}"

    except Exception as e:
        return f"Extraction failed: {str(e)}"


@mcp.tool()
def compress_to_archive_tool(package_path: str):
    """Compress <package_path>/extracted back into the archive it was extracted from"""
    if not _in_workspace(package_path):
        return _outside(package_path)
    try:
        if not package_path or not isinstance(package_path, str):
            return "Error: package_path must be valid string"

        if "extracted" in package_path:
            return f"Error: package_path should not contain 'extracted'"

        extracted_dir = os.path.join(package_path, "extracted")
        if not os.path.exists(extracted_dir):
            return f"Error: Extracted directory '{extracted_dir}' not found"

        record = server_state["extractions"].get(os.path.realpath(package_path))
        original_archive = None
        original_fmt = None
        if record and os.path.exists(record["archive"]):
            original_archive = record["archive"]
            original_fmt = get_archive_format(original_archive)[0]
        else:
            for item in sorted(os.listdir(package_path)):
                item_path = os.path.join(package_path, item)
                if os.path.isfile(item_path):
                    fmt, _ = get_archive_format(item_path)
                    if fmt:
                        original_archive = item_path
                        original_fmt = fmt
                        break

        if not original_archive:
            return f"Error: No original archive in '{package_path}'"

        original_filename = os.path.basename(original_archive)
        if record and record["fingerprint"] == _fingerprint(extracted_dir):
            shutil.rmtree(extracted_dir)
            server_state["extractions"].pop(os.path.realpath(package_path), None)
            return (f"No files inside {extracted_dir} changed; kept the original archive "
                    f"{original_filename} and removed extracted/.")

        output_archive = os.path.join(package_path, f"{original_filename}")

        if os.path.exists(output_archive):
            os.remove(output_archive)

        if original_fmt in ["tar.gz", "tar.xz", "tar.bz2"]:
            mode = SUPPORTED_FORMATS[original_fmt]["mode"].replace("r", "w")
            with tarfile.open(output_archive, mode) as tar:
                for item in os.listdir(extracted_dir):
                    item_path = os.path.join(extracted_dir, item)
                    tar.add(item_path, arcname=item)
        elif original_fmt == "zip":
            with zipfile.ZipFile(output_archive, "w", zipfile.ZIP_DEFLATED) as zip_ref:
                for root, _, files in os.walk(extracted_dir):
                    for file in files:
                        file_path = os.path.join(root, file)
                        arcname = os.path.relpath(file_path, extracted_dir)
                        zip_ref.write(file_path, arcname)

        shutil.rmtree(extracted_dir)
        server_state["extractions"].pop(os.path.realpath(package_path), None)
        return f"Success: Compressed to {output_archive}"

    except Exception as e:
        return f"Compression failed: {str(e)}"


@mcp.tool()
def upload_file_to_obs_tool(package_path: str):
    """Upload repaired package to OBS"""
    if not _in_workspace(package_path):
        return _outside(package_path)
    if not os.path.isdir(package_path):
        return f"Error: '{package_path}' is not a directory"

    recipe = case_type(package_path) == "recipe"
    has_spec = any(
        f.endswith(".spec")
        for f in os.listdir(package_path)
        if os.path.isfile(os.path.join(package_path, f))
    )
    if not has_spec and not recipe:
        return f"Error: No .spec file in '{package_path}'"

    package_name = os.path.basename(package_path)
    try:
        cfg = load_obs_config()
        if recipe:
            obs_result = script_upload(package_name, package_path, cfg)
        elif cfg["backend"] == "local":
            obs_result = local_upload(package_name, package_path, cfg)
        else:
            obs_result = main_upload(package_name, package_path)
        if "error" in str(obs_result).lower():
            return f"Upload failed: {obs_result}"
        return f"Upload successful. Result: {obs_result}"
    except Exception as e:
        return f"Upload error: {str(e)}"


@mcp.tool()
def check_build_result(input_dir: str, package_name: str):
    """Check build result in OBS"""
    if not _in_workspace(input_dir):
        return _outside(input_dir)
    try:
        cfg = load_obs_config()
        if case_type(input_dir) == "recipe":
            obs_result = script_check(input_dir, package_name, cfg)
        elif cfg["backend"] == "local":
            obs_result = local_check(input_dir, package_name, cfg)
        else:
            obs_result = check_main(input_dir, package_name)
        return f"Build result: {obs_result}"
    except Exception as e:
        return f"Build check error: {str(e)}"


@mcp.tool()
def get_packages_to_process(base_dir: str, result_dir: str) -> str:
    """
    obtain the packages to process
    Args:
        base_dir: the base directory
        result_dir: the result storge directory
    Returns:
        a JSON string, containing the package list
    """
    try:
        if not os.path.exists(base_dir):
            return json.dumps(
                {
                    "success": False,
                    "message": f"Base directory not found: {base_dir}",
                    "packages": [],
                }
            )

        packages = [
            item
            for item in os.listdir(base_dir)
            if os.path.isdir(os.path.join(base_dir, item))
        ]

        return json.dumps(
            {
                "success": True,
                "message": f"Found {len(packages)} packages",
                "packages": packages,
            }
        )
    except Exception as e:
        return json.dumps(
            {
                "success": False,
                "message": f"Error getting packages: {str(e)}",
                "packages": [],
            }
        )


if __name__ == "__main__":
    mcp.run(transport="stdio")
