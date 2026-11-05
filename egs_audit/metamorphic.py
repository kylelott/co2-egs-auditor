"""Invariance, scaling, monotonicity, smoothness and convergence tests.

These need no reference answer, only a callable model ``model(inputs: dict) -> outputs: dict``.
Wrap the simulator in such a callable (see adapter.py / AUDIT_PROMPT.md) and run these.
"""

from __future__ import annotations

import copy
from typing import Callable, Mapping, Sequence

from .checks import CheckResult, FAIL, PASS, TOL, WARN

Model = Callable[[dict], Mapping[str, float]]


def _set(inputs, key, value):
    out = copy.deepcopy(inputs)
    out[key] = value
    return out


def scaling(model: Model, inputs: dict, keys: Sequence[str], factor: float, output: str,
            expected_ratio: float, tol=TOL["exact"], name=None):
    """Multiply ``keys`` by ``factor``; ``output`` must change by ``expected_ratio``.

    Examples: all cost inputs x2 -> LCOE x2. All extensive plant inputs x2 -> LCOE x1.
    """
    base = model(inputs)[output]
    mod = copy.deepcopy(inputs)
    for k in keys:
        v = mod[k]
        mod[k] = [x * factor for x in v] if isinstance(v, (list, tuple)) else v * factor
    new = model(mod)[output]
    ratio = new / base
    res = abs(ratio - expected_ratio) / abs(expected_ratio)
    return CheckResult(name or f"Scale {list(keys)} x{factor} -> {output} x{expected_ratio}",
                       "C. invariance", PASS if res <= tol else FAIL, res, tol,
                       f"base={base:.6g}, scaled={new:.6g}, ratio={ratio:.6g}")


def invariance(model: Model, inputs: dict, transform: Callable[[dict], dict], output: str,
               tol=TOL["exact"], name="Invariance"):
    """``output`` must not change under ``transform`` (e.g. a unit change of an input)."""
    a = model(inputs)[output]
    b = model(transform(copy.deepcopy(inputs)))[output]
    res = abs(a - b) / max(abs(a), 1e-30)
    return CheckResult(name, "C. invariance", PASS if res <= tol else FAIL, res, tol,
                       f"before={a:.8g}, after={b:.8g}")


def sweep(model: Model, inputs: dict, key: str, values: Sequence[float], output: str):
    return [model(_set(inputs, key, v))[output] for v in values]


def monotonic(model: Model, inputs: dict, key: str, values: Sequence[float], output: str,
              direction: str, name=None):
    """``output`` must be non-decreasing ("up") or non-increasing ("down") as ``key`` rises."""
    ys = sweep(model, inputs, key, values, output)
    viol = []
    for i in range(1, len(ys)):
        d = ys[i] - ys[i - 1]
        if (direction == "up" and d < 0) or (direction == "down" and d > 0):
            viol.append(f"{key}: {values[i - 1]:.4g}->{values[i]:.4g}, {output}: "
                        f"{ys[i - 1]:.4g}->{ys[i]:.4g}")
    return CheckResult(name or f"{output} {direction} with {key}", "E. sweeps",
                       FAIL if viol else PASS, None, None,
                       "; ".join(viol[:5]) or f"monotone over {len(values)} points")


def kinks(xs: Sequence[float], ys: Sequence[float], threshold=5.0, name="Smoothness (kinks)"):
    """Flag points where the local second difference is far above the series' typical one.

    Kinks/jumps usually come from phase-boundary handling, if/else branches, unconverged
    solvers or coarse interpolation tables. Uses a robust (median) scale.
    """
    if len(ys) < 5:
        return CheckResult(name, "E. sweeps", WARN, detail="need >= 5 points")
    slopes = [(ys[i + 1] - ys[i]) / (xs[i + 1] - xs[i]) for i in range(len(ys) - 1)]
    d2 = [abs(slopes[i + 1] - slopes[i]) for i in range(len(slopes) - 1)]
    med = sorted(d2)[len(d2) // 2]
    scale = med if med > 0 else (max(abs(s) for s in slopes) or 1.0) * 1e-9
    flagged = [(xs[i + 1], d2[i] / scale) for i in range(len(d2)) if d2[i] > threshold * scale]
    return CheckResult(name, "E. sweeps", WARN if flagged else PASS, None, threshold,
                       ("possible kinks at x = " + ", ".join(f"{x:.4g} ({r:.0f}x)" for x, r in flagged[:6]))
                       if flagged else "no kinks detected")


def convergence(model: Model, inputs: dict, key: str, resolutions: Sequence[int], output: str,
                tol=TOL["discretized"], name=None):
    """Refine a resolution input (segments, time steps); successive changes must shrink and the
    finest two must agree within ``tol``. Also returns a Richardson-style observed order."""
    ys = sweep(model, inputs, key, resolutions, output)
    diffs = [abs(ys[i + 1] - ys[i]) for i in range(len(ys) - 1)]
    shrinking = all(diffs[i + 1] <= diffs[i] * 1.05 for i in range(len(diffs) - 1))
    last = diffs[-1] / max(abs(ys[-1]), 1e-30)
    order = None
    if len(diffs) >= 2 and diffs[-1] > 0 and diffs[-2] > 0:
        import math
        ratio = resolutions[-1] / resolutions[-2]
        order = math.log(diffs[-2] / diffs[-1]) / math.log(ratio)
    ok = shrinking and last <= tol
    return CheckResult(name or f"Convergence of {output} in {key}", "C. invariance",
                       PASS if ok else FAIL, last, tol,
                       f"values={[f'{y:.6g}' for y in ys]}; observed order={order}")


def elasticity(model: Model, inputs: dict, key: str, output: str, rel_step=0.01):
    """d ln(output) / d ln(input) by central difference."""
    x = inputs[key]
    up = model(_set(inputs, key, x * (1 + rel_step)))[output]
    dn = model(_set(inputs, key, x * (1 - rel_step)))[output]
    base = model(inputs)[output]
    return (up - dn) / (2 * rel_step * base)


def variance_bridge(model: Model, case_a: dict, case_b: dict, output: str, keys: Sequence[str]):
    """Decompose output(B) - output(A) into one-at-a-time contributions of each changed key.

    Returns (contributions dict, interaction residual). A large residual relative to the total
    means strong interactions OR an inconsistency in how inputs flow through the model.
    """
    ya, yb = model(case_a)[output], model(case_b)[output]
    contrib = {}
    for k in keys:
        contrib[k] = model(_set(case_a, k, case_b[k]))[output] - ya
    residual = (yb - ya) - sum(contrib.values())
    return {"total_change": yb - ya, "contributions": contrib, "interaction_residual": residual}
