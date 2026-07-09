#!/usr/bin/env python3
"""Summarize Hermes context budget metrics from agent.log."""

from __future__ import annotations

import argparse
import ast
import os
from pathlib import Path
from statistics import median
from typing import Iterable, List


def _percentile(values: List[int], pct: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    idx = int(round((len(ordered) - 1) * pct))
    return ordered[max(0, min(idx, len(ordered) - 1))]


def _default_log_path() -> Path:
    home = os.getenv("HERMES_HOME") or os.path.expanduser("~/.hermes")
    return Path(home) / "logs" / "agent.log"


def iter_metrics(lines: Iterable[str]):
    marker = "context_budget "
    for line in lines:
        if marker not in line:
            continue
        raw = line.split(marker, 1)[1].strip()
        try:
            data = ast.literal_eval(raw)
        except (SyntaxError, ValueError):
            continue
        if isinstance(data, dict):
            yield data


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log", nargs="?", type=Path, default=_default_log_path())
    parser.add_argument("--last", type=int, default=200, help="Analyze only the last N context_budget records")
    args = parser.parse_args()

    if not args.log.exists():
        print(f"No log file found: {args.log}")
        return 1

    records = list(iter_metrics(args.log.read_text(errors="replace").splitlines()))
    if args.last > 0:
        records = records[-args.last:]
    if not records:
        print("No context_budget records found.")
        return 0

    before = [int(r.get("before_tokens") or 0) for r in records]
    after = [int(r.get("after_tokens") or 0) for r in records]
    removed = [int(r.get("removed_tokens") or 0) for r in records]
    trimmed = [r for r in records if r.get("reason") == "trimmed"]
    hits = [r for r in records if r.get("budget_hit")]
    target = max(int(r.get("target_input_tokens") or 0) for r in records)

    print(f"records: {len(records)}")
    print(f"target_input_tokens_max: {target:,}")
    print(f"trimmed_requests: {len(trimmed)} ({len(trimmed) / len(records):.1%})")
    print(f"budget_hit_requests: {len(hits)} ({len(hits) / len(records):.1%})")
    print(f"before_tokens_p50/p95/max: {int(median(before)):,} / {_percentile(before, 0.95):,} / {max(before):,}")
    print(f"after_tokens_p50/p95/max: {int(median(after)):,} / {_percentile(after, 0.95):,} / {max(after):,}")
    print(f"removed_tokens_total: {sum(removed):,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

