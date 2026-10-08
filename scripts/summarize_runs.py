"""Summarize archived benchmark runs.

Usage: python scripts/summarize_runs.py <result_dir> [run_prefix]
Reads <result_dir>/<run>/*_result.json and prints one row per package and run,
followed by the success rate and mean cost of each run prefix.
"""
import glob
import json
import os
import sys
from collections import defaultdict

result_dir = sys.argv[1]
prefix = sys.argv[2] if len(sys.argv) > 2 else ""

rows = []
for path in sorted(glob.glob(os.path.join(result_dir, f"{prefix}*", "*_result.json"))):
    with open(path) as f:
        d = json.load(f)
    run = os.path.basename(os.path.dirname(path))
    rows.append((run, d))

header = f"{'run':<28} {'package':<20} {'ok':<4} {'att':<4} {'by':<10} {'min':>6} {'calls':>6} {'cost $':>8}"
print(header)
print("-" * len(header))
groups = defaultdict(list)
for run, d in rows:
    print(f"{run:<28} {d['package']:<20} {'yes' if d['success'] else 'no':<4} "
          f"{str(d.get('success_attempt') or '-'):<4} {str(d.get('success_verified_by') or '-'):<10} "
          f"{d['minutes']:>6} {d['llm_calls']:>6} {d['cost_usd']:>8.4f}")
    groups[run.rsplit("_", 1)[0]].append(d)

print()
for group, ds in groups.items():
    ok = sum(d["success"] for d in ds)
    cost = sum(d["cost_usd"] for d in ds) / len(ds)
    print(f"{group}: {ok}/{len(ds)} successful, mean cost ${cost:.4f}")
