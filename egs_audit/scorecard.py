"""Render a list of CheckResults as the pass/fail scorecard that opens an audit report."""

from __future__ import annotations

from collections import Counter

from .checks import FAIL, PASS, SKIP, WARN


def _fmt(x):
    if x is None:
        return "-"
    if isinstance(x, float):
        return f"{x:.3g}"
    return str(x)


def to_markdown(results, title="Validation scorecard") -> str:
    c = Counter(r.status for r in results)
    lines = [f"## {title}", "",
             f"**{c[PASS]} pass, {c[FAIL]} fail, {c[WARN]} warn, {c[SKIP]} skipped** "
             f"out of {len(results)} checks.", ""]
    order = {FAIL: 0, WARN: 1, PASS: 2, SKIP: 3}
    rs = sorted(results, key=lambda r: (order.get(r.status, 9), r.group, r.name))
    lines += ["| Status | Group | Check | Residual | Tolerance | Detail |",
              "|---|---|---|---|---|---|"]
    for r in rs:
        mark = {FAIL: "**FAIL**", WARN: "WARN", PASS: "PASS", SKIP: "SKIP"}[r.status]
        det = r.detail.replace("|", "/")
        if len(det) > 220:
            det = det[:217] + "..."
        lines.append(f"| {mark} | {r.group} | {r.name} | {_fmt(r.residual)} | "
                     f"{_fmt(r.tolerance)} | {det} |")
    lines.append("")
    if c[FAIL]:
        lines += ["Each FAIL is a lead, not yet a finding: localize it (per component / per "
                  "year / per calc-sheet step), then diagnose with a hand-check and code read.", ""]
    return "\n".join(lines)


def summary(results):
    c = Counter(r.status for r in results)
    return {s: c[s] for s in (PASS, FAIL, WARN, SKIP)}
