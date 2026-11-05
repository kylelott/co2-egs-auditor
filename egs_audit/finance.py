"""Independent year-by-year cash-flow engine for LCOE / NPV / IRR.

Design goals: transparent (every line of the cash-flow table is exposed), correct real-vs-nominal
handling, and enough features to reproduce typical CO2-EGS TEAs (construction period, thermal
drawdown via a year-by-year energy series, CO2 purchase/make-up, time-limited credits such as
45Q, income tax and MACRS depreciation, decommissioning).

Conventions (stated, not hidden)
--------------------------------
* Time index t: cash flows occur at the END of year t, discounted by 1/(1+i)^t
  (or 1/(1+i)^(t-0.5) with ``mid_year=True`` for operating flows).
* Capital is spent at t = 0 .. Nc-1 (Nc = len(capex_real_usd)). Operations run at
  t = Nc .. Nc+n-1. With a single capex entry this is the textbook "capex at t=0, energy at
  t=1..n" case, which is the case the CRF shortcut is valid for.
* All cost/credit inputs are REAL, in base-year (t=0) dollars, and escalate with inflation to
  get nominal dollars: X_nom(t) = X_real(t) * (1+inflation)^t. Depreciation is computed on the
  nominal capex and is NOT escalated afterwards (this is exactly why real vs nominal matters
  once taxes are included).
* Discounting uses the nominal rate i = (1+r_real)(1+inflation) - 1 on nominal cash flows.
  Discounting real flows at r_real gives the identical NPV; mixing them is a bug.
* Taxes: tax = tax_rate * taxable income, and negative tax (losses) is assumed usable in the
  year it arises (``tax_losses_usable=True``). Tax credits (45Q, PTC, ITC) are NOT taxable income.
* LCOE is the price that makes after-tax NPV exactly zero. NPV is linear in price, so it is
  solved exactly (no iteration). Two flavours:
    - real LCOE: a price constant in real terms (escalates with inflation in nominal terms)
    - nominal levelized LCOE: a price constant in nominal terms
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

# IRS MACRS, half-year convention (fractions of basis per year). Source: IRS Publication 946,
# Table A-1. Geothermal property generally falls in the 5-year class; verify for your case.
MACRS = {
    3: [0.3333, 0.4445, 0.1481, 0.0741],
    5: [0.20, 0.32, 0.192, 0.1152, 0.1152, 0.0576],
    7: [0.1429, 0.2449, 0.1749, 0.1249, 0.0893, 0.0892, 0.0893, 0.0446],
    15: [0.05, 0.095, 0.0855, 0.077, 0.0693, 0.0623, 0.059, 0.059, 0.0591, 0.059, 0.0591,
         0.059, 0.0591, 0.059, 0.0591, 0.0295],
    20: [0.0375, 0.07219, 0.06677, 0.06177, 0.05713, 0.05285, 0.04888, 0.04522, 0.04462,
         0.04461, 0.04462, 0.04461, 0.04462, 0.04461, 0.04462, 0.04461, 0.04462, 0.04461,
         0.04462, 0.04461, 0.02231],
}


def straight_line(years: int):
    return [1.0 / years] * years


def crf(rate: float, n: int) -> float:
    """Capital recovery factor r(1+r)^n / ((1+r)^n - 1); 1/n when rate == 0."""
    if rate == 0:
        return 1.0 / n
    a = (1 + rate) ** n
    return rate * a / (a - 1)


def nominal_rate(real_rate: float, inflation: float) -> float:
    """Fisher relation. The common approximation r_nom ~ r_real + inflation is NOT used."""
    return (1 + real_rate) * (1 + inflation) - 1


def real_rate(nominal: float, inflation: float) -> float:
    return (1 + nominal) / (1 + inflation) - 1


def simple_lcoe(overnight_capex, rate, n, fixed_om, annual_MWh, variable_om_per_MWh=0.0,
                annual_other=0.0):
    """Textbook LCOE = (CRF*capex + FOM + other)/E + VOM. Pre-tax, constant output only."""
    return (crf(rate, n) * overnight_capex + fixed_om + annual_other) / annual_MWh + variable_om_per_MWh


def npv(rate: float, cashflows: Sequence[float], times: Sequence[float] | None = None) -> float:
    times = range(len(cashflows)) if times is None else times
    return sum(cf / (1 + rate) ** t for cf, t in zip(cashflows, times))


def irr(cashflows: Sequence[float], lo=-0.99, hi=1.0, tol=1e-10, max_iter=500) -> float:
    """IRR by bisection. Raises if there is no sign change in [lo, hi] (no unique IRR found)."""
    f_lo, f_hi = npv(lo, cashflows), npv(hi, cashflows)
    if f_lo * f_hi > 0:
        raise ValueError("no IRR bracketed in the search interval")
    for _ in range(max_iter):
        mid = 0.5 * (lo + hi)
        f_mid = npv(mid, cashflows)
        if abs(f_mid) < tol or (hi - lo) < tol:
            return mid
        if f_lo * f_mid < 0:
            hi, f_hi = mid, f_mid
        else:
            lo, f_lo = mid, f_mid
    raise RuntimeError("IRR bisection did not converge")


def _as_series(x, n):
    if isinstance(x, (int, float)):
        return [float(x)] * n
    x = list(x)
    if len(x) != n:
        raise ValueError(f"series length {len(x)} != {n} operating years")
    return [float(v) for v in x]


@dataclass
class FinanceInputs:
    capex_real_usd: Sequence[float]            # spent at t = 0..Nc-1, base-year $
    annual_energy_MWh: Sequence[float]         # NET generation per operating year (length n)
    real_discount_rate: float
    inflation: float = 0.0
    fixed_om_real_usd: float | Sequence[float] = 0.0
    variable_om_real_usd_per_MWh: float = 0.0
    other_costs_real_usd: float | Sequence[float] = 0.0      # e.g. make-up CO2 purchase
    credits_real_usd: float | Sequence[float] = 0.0          # e.g. 45Q $/yr (non-taxable)
    credits_escalate: bool = True     # False -> credits fixed in nominal $ (not inflation-indexed)
    tax_rate: float = 0.0
    depreciation_schedule: Sequence[float] = field(default_factory=list)  # fractions, sum to 1
    depreciable_fraction: float = 1.0
    itc_rate: float = 0.0             # investment tax credit, paid in first operating year
    itc_basis_reduction: float = 0.5  # US rule: basis reduced by 50% of the ITC
    decommissioning_real_usd: float = 0.0     # in the last operating year, tax-deductible
    mid_year: bool = False
    tax_losses_usable: bool = True

    @property
    def n(self):
        return len(self.annual_energy_MWh)

    @property
    def n_construction(self):
        return len(self.capex_real_usd)


@dataclass
class FinanceResult:
    table: list                      # one dict per year t
    lcoe_real: float                 # $/MWh in base-year dollars
    lcoe_nominal_levelized: float    # $/MWh, constant nominal
    npv_at_lcoe: float               # should be ~0 (definitional check)
    nominal_rate: float
    pv_energy_real: float            # sum E_t / (1+r_real)^t
    pv_costs_pretax_real: float      # PV of capex+opex+other+decom - credits, real rate
    simple_pretax_lcoe_real: float   # pv_costs_pretax_real / pv_energy_real


def _build(inp: FinanceInputs, price_real: float | None, price_nominal: float | None):
    """Build the cash-flow table for a given price (exactly one of the two prices is set)."""
    n, nc = inp.n, inp.n_construction
    pi_ = inp.inflation
    i_nom = nominal_rate(inp.real_discount_rate, pi_)
    E = [float(e) for e in inp.annual_energy_MWh]
    fom = _as_series(inp.fixed_om_real_usd, n)
    oth = _as_series(inp.other_costs_real_usd, n)
    cred = _as_series(inp.credits_real_usd, n)
    sched = list(inp.depreciation_schedule)

    capex_nom = [c * (1 + pi_) ** t for t, c in enumerate(inp.capex_real_usd)]
    total_capex_nom = sum(capex_nom)
    itc = inp.itc_rate * total_capex_nom
    basis = inp.depreciable_fraction * total_capex_nom - inp.itc_basis_reduction * itc

    T = nc + n
    rows = []
    for t in range(T):
        op = t - nc                      # operating-year index, <0 during construction
        # mid-year convention: operating flows occur at t-0.5, so escalate AND discount there
        dt = t - 0.5 if (inp.mid_year and op >= 0) else t
        esc = (1 + pi_) ** dt
        df = 1.0 / (1 + i_nom) ** dt
        r = {"t": t, "op_year": op + 1 if op >= 0 else 0, "discount_factor": df,
             "capex": capex_nom[t] if t < nc else 0.0}
        if op >= 0:
            e = E[op]
            price = price_real * esc if price_real is not None else price_nominal
            r["energy_MWh"] = e
            r["price"] = price
            r["revenue"] = price * e
            r["fixed_om"] = fom[op] * esc
            r["variable_om"] = inp.variable_om_real_usd_per_MWh * e * esc
            r["other_costs"] = oth[op] * esc
            r["decommissioning"] = inp.decommissioning_real_usd * esc if op == n - 1 else 0.0
            r["depreciation"] = basis * sched[op] if op < len(sched) else 0.0
            r["credits"] = cred[op] * (esc if inp.credits_escalate else 1.0)
            r["itc"] = itc if op == 0 else 0.0
        else:
            for k in ("energy_MWh", "price", "revenue", "fixed_om", "variable_om", "other_costs",
                      "decommissioning", "depreciation", "credits", "itc"):
                r[k] = 0.0
        opex = r["fixed_om"] + r["variable_om"] + r["other_costs"] + r["decommissioning"]
        r["opex"] = opex
        r["taxable_income"] = r["revenue"] - opex - r["depreciation"]
        tax = inp.tax_rate * r["taxable_income"]
        if not inp.tax_losses_usable:
            tax = max(tax, 0.0)
        r["tax"] = tax
        r["cash_flow"] = r["revenue"] - opex - r["capex"] - tax + r["credits"] + r["itc"]
        r["pv_cash_flow"] = r["cash_flow"] * df
        rows.append(r)
    return rows, i_nom


def evaluate(inp: FinanceInputs, price_real: float | None = None,
             price_nominal: float | None = None):
    """Cash-flow table and NPV at a given price."""
    if (price_real is None) == (price_nominal is None):
        raise ValueError("give exactly one of price_real / price_nominal")
    rows, i_nom = _build(inp, price_real, price_nominal)
    return rows, sum(r["pv_cash_flow"] for r in rows)


def solve(inp: FinanceInputs) -> FinanceResult:
    if inp.depreciation_schedule and abs(sum(inp.depreciation_schedule) - 1) > 1e-3:
        raise ValueError("depreciation schedule does not sum to 1")
    if inp.tax_rate > 0 and not inp.depreciation_schedule:
        raise ValueError("tax_rate > 0 but no depreciation schedule: capital would never be "
                         "deducted. Pass a schedule explicitly (e.g. MACRS[5]).")
    # NPV(p) = A + B p  (exact when tax losses are usable)
    _, A_r = evaluate(inp, price_real=0.0)
    _, B1_r = evaluate(inp, price_real=1.0)
    lcoe_r = -A_r / (B1_r - A_r)
    _, A_n = evaluate(inp, price_nominal=0.0)
    _, B1_n = evaluate(inp, price_nominal=1.0)
    lcoe_n = -A_n / (B1_n - A_n)
    rows, npv0 = evaluate(inp, price_real=lcoe_r)
    if not inp.tax_losses_usable:
        # NPV is piecewise linear; refine by secant so the definitional check still holds
        lo, hi = lcoe_r, lcoe_r * 1.5 + 1.0
        for _ in range(200):
            _, f_lo = evaluate(inp, price_real=lo)
            _, f_hi = evaluate(inp, price_real=hi)
            if f_hi == f_lo:
                break
            new = hi - f_hi * (hi - lo) / (f_hi - f_lo)
            lo, hi = hi, new
            if abs(new - lo) < 1e-12:
                break
        lcoe_r = hi
        rows, npv0 = evaluate(inp, price_real=lcoe_r)

    # Independent pre-tax real-terms calculation (no table reuse) for reconciliation
    r = inp.real_discount_rate
    nc, n = inp.n_construction, inp.n
    fom = _as_series(inp.fixed_om_real_usd, n)
    oth = _as_series(inp.other_costs_real_usd, n)
    cred = _as_series(inp.credits_real_usd, n)
    pv_c, pv_e = 0.0, 0.0
    for t, c in enumerate(inp.capex_real_usd):
        pv_c += c / (1 + r) ** t
    for k in range(n):
        t = nc + k
        tt = t - 0.5 if inp.mid_year else t
        dfr = 1 / (1 + r) ** tt
        e = inp.annual_energy_MWh[k]
        cost = fom[k] + inp.variable_om_real_usd_per_MWh * e + oth[k]
        if k == n - 1:
            cost += inp.decommissioning_real_usd
        credit = cred[k] if inp.credits_escalate else cred[k] / (1 + inp.inflation) ** tt
        pv_c += (cost - credit) * dfr
        pv_e += e * dfr
    return FinanceResult(rows, lcoe_r, lcoe_n, npv0, nominal_rate(r, inp.inflation), pv_e, pv_c,
                         pv_c / pv_e)


def format_table(rows, columns=("t", "op_year", "energy_MWh", "price", "revenue", "capex",
                                 "opex", "depreciation", "tax", "credits", "cash_flow",
                                 "discount_factor", "pv_cash_flow")) -> str:
    head = "| " + " | ".join(columns) + " |\n|" + "---|" * len(columns) + "\n"
    body = ""
    for r in rows:
        cells = []
        for c in columns:
            v = r.get(c, "")
            cells.append(f"{v:,.4g}" if isinstance(v, float) else str(v))
        body += "| " + " | ".join(cells) + " |\n"
    return head + body
