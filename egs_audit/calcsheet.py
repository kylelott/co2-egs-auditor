"""Step-by-step hand-check sheets.

A CalcSheet is an ordered chain of steps. Each step records the equation, its source, the
inputs (with units), the independently computed result, and optionally the simulator's value
for the same quantity. Rendering gives a page a reviewer can follow with a calculator.
Comparing step by step localizes the FIRST step where the simulator diverges.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .checks import CheckResult, FAIL, PASS, SKIP, TOL


@dataclass
class Step:
    id: str
    quantity: str
    equation: str
    result: float
    unit: str
    source: str = ""
    inputs: dict = field(default_factory=dict)   # name -> (value, unit)
    sim_value: float | None = None
    tol_class: str = "exact"
    note: str = ""

    @property
    def rel_diff(self):
        if self.sim_value is None:
            return None
        return abs(self.sim_value - self.result) / max(abs(self.result), 1e-30)

    @property
    def status(self):
        if self.sim_value is None:
            return SKIP
        return PASS if self.rel_diff <= TOL[self.tol_class] else FAIL


@dataclass
class CalcSheet:
    title: str
    case: str = ""
    steps: list = field(default_factory=list)

    def add(self, *args, **kwargs) -> Step:
        s = Step(*args, **kwargs)
        self.steps.append(s)
        return s

    def value(self, step_id):
        for s in self.steps:
            if s.id == step_id:
                return s.result
        raise KeyError(step_id)

    def attach_simulator(self, sim_values: dict):
        """sim_values: step id -> simulator value (same units as the step)."""
        for s in self.steps:
            if s.id in sim_values:
                s.sim_value = float(sim_values[s.id])

    def first_divergence(self):
        for s in self.steps:
            if s.status == FAIL:
                return s
        return None

    def to_checks(self, group="F. hand-check"):
        out = []
        for s in self.steps:
            out.append(CheckResult(f"[{s.id}] {s.quantity}", group, s.status, s.rel_diff,
                                   TOL[s.tol_class], f"hand={s.result:.6g} {s.unit}, "
                                   f"sim={s.sim_value if s.sim_value is not None else 'n/a'}"))
        return out

    def to_markdown(self) -> str:
        md = [f"# Calc sheet: {self.title}", ""]
        if self.case:
            md += [f"**Case:** {self.case}", ""]
        div = self.first_divergence()
        if div:
            md += [f"> **First divergence from simulator: step `{div.id}` ({div.quantity}).** "
                   "Audit this step and its inputs first; later mismatches may be knock-on.", ""]
        md += ["| Step | Quantity | Hand value | Unit | Simulator | Diff | Tol | Status |",
               "|---|---|---|---|---|---|---|---|"]
        for s in self.steps:
            sim = f"{s.sim_value:.6g}" if s.sim_value is not None else "-"
            dif = f"{s.rel_diff:.3%}" if s.rel_diff is not None else "-"
            md.append(f"| {s.id} | {s.quantity} | {s.result:.6g} | {s.unit} | {sim} | {dif} | "
                      f"{TOL[s.tol_class]:.2g} ({s.tol_class}) | {s.status} |")
        md += ["", "## Worked steps", ""]
        for s in self.steps:
            md.append(f"### {s.id}. {s.quantity}")
            md.append("")
            md.append(f"- Equation: `{s.equation}`")
            if s.source:
                md.append(f"- Source: {s.source}")
            if s.inputs:
                ins = "; ".join(f"{k} = {v:.6g} {u}" if isinstance(v, (int, float)) else f"{k} = {v} {u}"
                                for k, (v, u) in s.inputs.items())
                md.append(f"- Inputs: {ins}")
            md.append(f"- Result: **{s.result:.6g} {s.unit}**")
            if s.note:
                md.append(f"- Note: {s.note}")
            md.append("")
        return "\n".join(md)
