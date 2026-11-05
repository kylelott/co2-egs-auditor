"""Balance, closure, tie-out and bound checks.

Every function returns a CheckResult. None of them need a "right answer": they test relations
that must hold if the model is correct (conservation laws, accounting identities, definitional
identities). A failure says WHERE to dig, not yet WHY.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Mapping

PASS, FAIL, SKIP, WARN = "PASS", "FAIL", "SKIP", "WARN"

# Tolerance classes (relative). Pick by the nature of the calculation, not by what passes.
TOL = {
    "exact": 1e-6,          # pure arithmetic: finance, footing, tie-outs
    "property": 1e-3,       # EOS / property lookups
    "discretized": 1e-2,    # integrated wellbore / reservoir quantities
    "balance": 5e-3,        # whole-system energy / mass closure in a numerical simulator
    "estimate": 0.25,       # back-of-envelope sanity estimates
}


@dataclass
class CheckResult:
    name: str
    group: str
    status: str
    residual: float | None = None   # relative unless ``units`` says otherwise
    tolerance: float | None = None
    detail: str = ""
    units: str = "rel"

    @property
    def passed(self):
        return self.status == PASS


def _rel(a, b, floor=1e-30):
    return abs(a - b) / max(abs(a), abs(b), floor)


def skip(name, group, why):
    return CheckResult(name, group, SKIP, detail=why)


def closure(name, lhs, rhs, tol=TOL["balance"], group="A. balance", detail=""):
    """Generic lhs == rhs within a relative tolerance."""
    res = _rel(lhs, rhs)
    st = PASS if res <= tol else FAIL
    return CheckResult(name, group, st, res, tol,
                       detail or f"lhs={lhs:.6g}, rhs={rhs:.6g}, diff={lhs - rhs:.6g}")


# ---------------------------------------------------------------- A. conservation balances

def energy_balance(Q_in, W_out, Q_rejected, W_in=0.0, Q_losses=0.0, tol=TOL["balance"],
                   name="Energy balance (1st law)"):
    """Steady loop: heat in + work in = work out + heat rejected + heat losses.

    Q_in: heat extracted from the reservoir (W). W_out: turbine (gross) work. W_in: all pump /
    compressor / fan work. Q_losses: wellbore or other heat losses to surroundings.
    """
    lhs = Q_in + W_in
    rhs = W_out + Q_rejected + Q_losses
    return closure(name, lhs, rhs, tol, detail=(
        f"in: Q_res={Q_in:.6g} + W_in={W_in:.6g} = {lhs:.6g}; out: W_out={W_out:.6g} + "
        f"Q_rej={Q_rejected:.6g} + Q_loss={Q_losses:.6g} = {rhs:.6g}; residual={lhs - rhs:.6g} W"))


def mass_balance(injected, produced, lost, inventory_change=0.0, tol=TOL["balance"],
                 name="Mass balance"):
    """injected = produced + lost + change in inventory (rates or cumulative totals)."""
    return closure(name, injected, produced + lost + inventory_change, tol, detail=(
        f"injected={injected:.6g}; produced={produced:.6g} + lost={lost:.6g} + "
        f"d_inventory={inventory_change:.6g}"))


def pressure_loop(segments: Mapping[str, float], tol=TOL["discretized"],
                  name="Pressure loop closure"):
    """Signed pressure changes around a closed circulation loop must sum to zero.

    Pass each segment's pressure change (outlet - inlet) in the flow direction, e.g.
    {"injection well": +dP, "reservoir": -dP, "production well": -dP, "turbine": -dP,
     "cooler": -dP, "pump": +dP}. Residual is relative to the largest |segment|.
    """
    total = sum(segments.values())
    scale = max(abs(v) for v in segments.values())
    res = abs(total) / scale
    parts = ", ".join(f"{k}={v / 1e6:+.4f} MPa" for k, v in segments.items())
    return CheckResult(name, "A. balance", PASS if res <= tol else FAIL, res, tol,
                       f"{parts}; sum={total / 1e6:+.5f} MPa")


def entropy_generation(components: Mapping[str, float], abs_tol=1e-6,
                       name="Entropy generation >= 0 (2nd law)"):
    """Each adiabatic component must have S_gen >= 0 (W/K). Negative => sign or eta error."""
    bad = {k: v for k, v in components.items() if v < -abs_tol}
    worst = min(components.values()) if components else 0.0
    return CheckResult(name, "A. balance", FAIL if bad else PASS, worst, -abs_tol,
                       ("negative in: " + ", ".join(f"{k}={v:.4g} W/K" for k, v in bad.items()))
                       if bad else "all components >= 0", units="W/K (min)")


def carbon_ledger(purchased_t, stored_t, vented_t=0.0, inventory_change_t=0.0, credited_t=None,
                  tol=TOL["exact"], name="Carbon ledger"):
    """purchased = stored + vented + inventory change; and credited <= stored."""
    r = closure(name, purchased_t, stored_t + vented_t + inventory_change_t, tol,
                group="A. balance", detail=(
                    f"purchased={purchased_t:.6g} t vs stored={stored_t:.6g} + "
                    f"vented={vented_t:.6g} + d_inv={inventory_change_t:.6g}"))
    if credited_t is not None and credited_t > stored_t * (1 + tol):
        r.status = FAIL
        r.detail += f"; CREDITED {credited_t:.6g} t > STORED {stored_t:.6g} t"
    return r


def sources_uses(sources: Mapping[str, float], uses: Mapping[str, float], tol=TOL["exact"],
                 name="Sources = uses"):
    return closure(name, sum(sources.values()), sum(uses.values()), tol, group="A. balance",
                   detail=f"sources={dict(sources)}; uses={dict(uses)}")


def balance_sheet(assets, liabilities, equity, tol=TOL["exact"], name="Balance sheet"):
    """assets = liabilities + equity, per year (sequences)."""
    worst, worst_t = 0.0, None
    for t, (a, l, e) in enumerate(zip(assets, liabilities, equity)):
        r = _rel(a, l + e)
        if r > worst:
            worst, worst_t = r, t
    return CheckResult(name, "A. balance", PASS if worst <= tol else FAIL, worst, tol,
                       f"worst year t={worst_t}")


# ---------------------------------------------------------------- B. accounting tie-outs

def footing(components: Mapping[str, float] | Iterable[float], total, tol=TOL["exact"],
            name="Footing"):
    vals = components.values() if isinstance(components, Mapping) else components
    s = sum(vals)
    return closure(name, s, total, tol, group="B. tie-out",
                   detail=f"sum of parts={s:.10g} vs reported total={total:.10g}")


def cross_footing(matrix, row_totals, col_totals, grand_total, tol=TOL["exact"],
                  name="Cross-footing"):
    """Rows sum to row totals, columns to column totals, and both to the grand total."""
    errs = []
    for i, (row, rt) in enumerate(zip(matrix, row_totals)):
        if _rel(sum(row), rt) > tol:
            errs.append(f"row {i}: {sum(row):.6g} != {rt:.6g}")
    for j, ct in enumerate(col_totals):
        cs = sum(row[j] for row in matrix)
        if _rel(cs, ct) > tol:
            errs.append(f"col {j}: {cs:.6g} != {ct:.6g}")
    if _rel(sum(row_totals), grand_total) > tol:
        errs.append(f"sum(row totals)={sum(row_totals):.6g} != grand={grand_total:.6g}")
    if _rel(sum(col_totals), grand_total) > tol:
        errs.append(f"sum(col totals)={sum(col_totals):.6g} != grand={grand_total:.6g}")
    return CheckResult(name, "B. tie-out", FAIL if errs else PASS, None, tol,
                       "; ".join(errs) or "rows, columns and grand total agree")


def roll_forward(opening, additions, deductions, closing, tol=TOL["exact"],
                 name="Roll-forward"):
    """closing[t] = opening[t] + additions[t] - deductions[t], and opening[t+1] = closing[t]."""
    errs = []
    for t in range(len(closing)):
        exp = opening[t] + additions[t] - deductions[t]
        if _rel(exp, closing[t]) > tol and abs(exp - closing[t]) > 1e-9:
            errs.append(f"t={t}: {exp:.6g} != closing {closing[t]:.6g}")
        if t + 1 < len(opening) and _rel(opening[t + 1], closing[t]) > tol \
                and abs(opening[t + 1] - closing[t]) > 1e-9:
            errs.append(f"t={t + 1}: opening {opening[t + 1]:.6g} != prior closing {closing[t]:.6g}")
    return CheckResult(name, "B. tie-out", FAIL if errs else PASS, None, tol,
                       "; ".join(errs[:5]) or "every period rolls forward")


def tie_out(reported: Mapping[str, float], model: Mapping[str, float], tol=TOL["exact"],
            name="Tie-out: reported vs model"):
    """Every reported number must equal the model output it claims to come from."""
    errs, missing = [], []
    for k, v in reported.items():
        if k not in model:
            missing.append(k)
        elif _rel(v, model[k]) > tol:
            errs.append(f"{k}: reported {v:.6g} vs model {model[k]:.6g} ({_rel(v, model[k]):.2%})")
    st = FAIL if errs or missing else PASS
    det = "; ".join(errs)
    if missing:
        det += ("; " if det else "") + "untraceable (no model value): " + ", ".join(missing)
    return CheckResult(name, "B. tie-out", st, None, tol, det or "all reported values tie out")


def two_path(name, a, b, tol=TOL["exact"], detail=""):
    """The same quantity computed two independent ways must agree."""
    return closure(name, a, b, tol, group="B. reconciliation", detail=detail or
                   f"path 1={a:.8g}, path 2={b:.8g}")


def npv_at_lcoe(npv_value, scale, tol=TOL["exact"], name="NPV at price = LCOE is zero"):
    """Definitional identity of LCOE. ``scale`` = e.g. total capex, to make it relative."""
    res = abs(npv_value) / abs(scale)
    return CheckResult(name, "B. reconciliation", PASS if res <= tol else FAIL, res, tol,
                       f"NPV={npv_value:.6g} $ (scale {scale:.4g} $)")


# ---------------------------------------------------------------- D. physical bounds

def carnot_bound(W_net, Q_in, T_hot, T_cold, name="Efficiency < Carnot"):
    eta = W_net / Q_in
    eta_c = 1 - T_cold / T_hot
    return CheckResult(name, "D. bounds", PASS if eta < eta_c else FAIL, eta / eta_c, 1.0,
                       f"eta={eta:.4f}, Carnot={eta_c:.4f} (T_hot={T_hot:.2f} K, "
                       f"T_cold={T_cold:.2f} K)", units="eta/eta_Carnot")


def exergy_bound(W_net, m_dot, h, s, h0, s0, T0, name="Net power <= exergy flow"):
    """W_net <= m (h - h0 - T0 (s - s0)) for the produced fluid relative to the dead state."""
    ex = m_dot * ((h - h0) - T0 * (s - s0))
    return CheckResult(name, "D. bounds", PASS if W_net <= ex else FAIL, W_net / ex, 1.0,
                       f"W_net={W_net / 1e6:.4f} MW, exergy={ex / 1e6:.4f} MW",
                       units="W_net/exergy")


def positivity(values: Mapping[str, float | Iterable[float]], name="Positivity"):
    bad = []
    for k, v in values.items():
        seq = v if isinstance(v, Iterable) else [v]
        for i, x in enumerate(seq):
            if not (x > 0) or math.isnan(x) or math.isinf(x):
                bad.append(f"{k}[{i}]={x}")
                break
    return CheckResult(name, "D. bounds", FAIL if bad else PASS, None, None,
                       ", ".join(bad) or "all strictly positive and finite")


def finite(values: Mapping[str, float | Iterable[float]], name="No NaN / inf"):
    bad = []
    for k, v in values.items():
        seq = v if isinstance(v, Iterable) else [v]
        if any(math.isnan(x) or math.isinf(x) for x in seq):
            bad.append(k)
    return CheckResult(name, "D. bounds", FAIL if bad else PASS, None, None,
                       ", ".join(bad) or "all finite")
