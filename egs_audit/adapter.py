"""Run every applicable check against a simulator's exported outputs.

The simulator (or a small wrapper the auditor writes) exports one JSON file following
``examples/simulator_outputs.example.json``. Every section is optional: checks whose data
is missing are reported as SKIP, so start with what is easy to export and add more.

Units in the JSON are SI and carried in key suffixes (``_Pa``, ``_K``, ``_J_kg``...).
"""

from __future__ import annotations

import json
import math

from . import checks as C
from . import properties as props
from . import turbo, wellbore
from .units import G


def load(path):
    with open(path) as fh:
        return json.load(fh)


def _get(d, *keys):
    for k in keys:
        if not isinstance(d, dict) or k not in d:
            return None
        d = d[k]
    return d


# ------------------------------------------------------------------ physics

def property_checks(sim):
    """Recompute density at every reported (P, T) state, and enthalpy DIFFERENCES between
    states (absolute enthalpies depend on each library's reference state)."""
    out = []
    states = sim.get("states") or {}
    if not states:
        return [C.skip("Property recomputation", "F. hand-check", "no 'states' exported")]
    ref_h = {}
    for name, st in states.items():
        P, T = st.get("P_Pa"), st.get("T_K")
        if P is None or T is None:
            continue
        try:
            ref = props.state_PT(P, T)
        except props.PropertyRangeError as exc:
            out.append(C.CheckResult(f"Property state '{name}'", "F. hand-check", C.WARN,
                                     detail=f"reference EOS undefined: {exc}"))
            continue
        ref_h[name] = ref.h
        note = " (NEAR CRITICAL)" if props.is_near_critical(P, T) else ""
        if "rho_kg_m3" in st:
            out.append(C.closure(f"Density at '{name}' vs Span-Wagner{note}", st["rho_kg_m3"],
                                 ref.rho, C.TOL["property"], group="F. hand-check"))
        if "mu_Pa_s" in st:
            out.append(C.closure(f"Viscosity at '{name}' vs CoolProp{note}", st["mu_Pa_s"],
                                 ref.mu, 0.02, group="F. hand-check"))
    names = [n for n in states if n in ref_h and "h_J_kg" in states[n]]
    for a, b in zip(names, names[1:]):
        dh_sim = states[b]["h_J_kg"] - states[a]["h_J_kg"]
        dh_ref = ref_h[b] - ref_h[a]
        out.append(C.CheckResult(
            f"Enthalpy difference '{a}'->'{b}' vs Span-Wagner", "F. hand-check",
            C.PASS if abs(dh_sim - dh_ref) <= max(C.TOL["property"] * max(abs(dh_ref), 1e4), 100)
            else C.FAIL, abs(dh_sim - dh_ref), max(C.TOL["property"] * max(abs(dh_ref), 1e4), 100),
            f"sim dh={dh_sim / 1e3:.4f} kJ/kg, ref dh={dh_ref / 1e3:.4f} kJ/kg", units="J/kg"))
    return out


def wellbore_checks(sim):
    out = []
    st = sim.get("states") or {}
    H = sim.get("depth_m")
    wells = sim.get("wells") or {}
    flows = sim.get("flows") or {}
    pairs = [("injection", "inj_wellhead", "inj_bottomhole", "down", flows.get("m_inj_kg_s")),
             ("production", "prod_bottomhole", "prod_wellhead", "up", flows.get("m_prod_kg_s"))]
    for label, a, b, direction, m in pairs:
        if a not in st or b not in st or H is None:
            out.append(C.skip(f"{label} well checks", "F. hand-check", "states or depth missing"))
            continue
        sa, sb = st[a], st[b]
        if "h_J_kg" in sa and "h_J_kg" in sb:
            dh = sb["h_J_kg"] - sa["h_J_kg"]
            exp = G * H if direction == "down" else -G * H
            r = C.closure(f"{label} well: dh = {'+' if direction == 'down' else '-'}gH "
                          "(adiabatic energy eq.)", dh, exp, C.TOL["discretized"],
                          group="F. hand-check",
                          detail=f"sim dh={dh / 1e3:.4f} kJ/kg, gH={exp / 1e3:.4f} kJ/kg. "
                                 "A mismatch is expected ONLY if the simulator models heat "
                                 "exchange with the formation; then check its sign and size.")
            out.append(r)
        D = wells.get("diameter_m")
        if D and m and "P_Pa" in sa and "T_K" in sa:
            try:
                res = wellbore.integrate_column(sa["P_Pa"], sa["T_K"], m, H, D,
                                                wells.get("roughness_m", 4.5e-5), 400, direction)
                out.append(C.closure(f"{label} well outlet pressure vs independent integration",
                                     sb["P_Pa"], res.outlet["P"], C.TOL["discretized"],
                                     group="F. hand-check",
                                     detail=f"sim={sb['P_Pa'] / 1e6:.4f} MPa, independent="
                                            f"{res.outlet['P'] / 1e6:.4f} MPa (adiabatic, Colebrook)"))
            except (props.PropertyRangeError, ValueError) as exc:
                out.append(C.CheckResult(f"{label} well re-integration", "F. hand-check", C.WARN,
                                         detail=str(exc)))
    return out


def turbine_checks(sim):
    st = sim.get("states") or {}
    eq = sim.get("equipment") or {}
    pw = sim.get("powers_W") or {}
    m = _get(sim, "flows", "m_prod_kg_s")
    if not all(k in st for k in ("prod_wellhead", "turbine_out")) or "eta_turbine" not in eq or m is None:
        return [C.skip("Turbine recomputation", "F. hand-check",
                       "needs states prod_wellhead/turbine_out, equipment.eta_turbine, m_prod")]
    a, b = st["prod_wellhead"], st["turbine_out"]
    tr = turbo.turbine(a["P_Pa"], a["T_K"], b["P_Pa"], eq["eta_turbine"], m)
    out = []
    if "W_turbine" in pw:
        out.append(C.closure("Turbine power vs independent isentropic-efficiency calc",
                             pw["W_turbine"], tr.power, C.TOL["property"], group="F. hand-check",
                             detail=f"sim={pw['W_turbine'] / 1e6:.4f} MW, independent="
                                    f"{tr.power / 1e6:.4f} MW"))
    if "T_K" in b:
        out.append(C.closure("Turbine outlet temperature vs independent calc", b["T_K"], tr.T_out,
                             C.TOL["property"], group="F. hand-check"))
    return out


def balance_checks(sim):
    out = []
    pw = sim.get("powers_W") or {}
    if {"Q_reservoir", "W_turbine", "Q_rejected"} <= pw.keys():
        out.append(C.energy_balance(pw["Q_reservoir"], pw["W_turbine"], pw["Q_rejected"],
                                    W_in=pw.get("W_pumps", 0.0) + pw.get("W_compressors", 0.0),
                                    Q_losses=pw.get("Q_losses", 0.0)))
    else:
        out.append(C.skip("Energy balance", "A. balance", "needs Q_reservoir, W_turbine, Q_rejected"))
    if {"W_gross", "W_net"} <= pw.keys():
        para = sum(pw.get(k, 0.0) for k in ("W_pumps", "W_compressors", "W_fans", "W_auxiliary"))
        out.append(C.two_path("Net power = gross - all parasitics", pw["W_net"], pw["W_gross"] - para,
                              C.TOL["exact"], detail=f"W_net={pw['W_net']:.6g}, W_gross - parasitics"
                                                     f"={pw['W_gross'] - para:.6g} (parasitics={para:.6g})"))
    fl = sim.get("flows") or {}
    if {"m_inj_kg_s", "m_prod_kg_s"} <= fl.keys():
        out.append(C.mass_balance(fl["m_inj_kg_s"], fl["m_prod_kg_s"], fl.get("m_loss_kg_s", 0.0),
                                  fl.get("inventory_change_kg_s", 0.0)))
    if sim.get("pressure_segments_Pa"):
        out.append(C.pressure_loop(sim["pressure_segments_Pa"]))
    if sim.get("entropy_generation_W_K"):
        out.append(C.entropy_generation(sim["entropy_generation_W_K"]))
    st = sim.get("states") or {}
    if "W_net" in pw and "Q_reservoir" in pw and "prod_bottomhole" in st and sim.get("T_ambient_K"):
        out.append(C.carnot_bound(pw["W_net"], pw["Q_reservoir"], st["prod_bottomhole"]["T_K"],
                                  sim["T_ambient_K"]))
    if "W_net" in pw and "prod_wellhead" in st and sim.get("T_ambient_K") and "m_prod_kg_s" in fl:
        w = st["prod_wellhead"]
        ref = props.state_PT(w["P_Pa"], w["T_K"])
        dead = props.state_PT(101325.0, sim["T_ambient_K"])
        out.append(C.exergy_bound(pw["W_net"], fl["m_prod_kg_s"], ref.h, ref.s, dead.h, dead.s,
                                  dead.T))
    numbers = {k: v for k, v in pw.items()}
    numbers.update({f"{n}.{k}": v for n, s in st.items() for k, v in s.items()})
    if numbers:
        out.append(C.finite(numbers))
    return out


# ------------------------------------------------------------------ finance

def _table(sim):
    return sim.get("cash_flow_table") or []


def cashflow_checks(sim):
    rows = _table(sim)
    fin = sim.get("finance") or {}
    if not rows:
        return [C.skip("Cash-flow checks", "B. tie-out", "no cash_flow_table exported")]
    out = []
    # per-row footing: cash_flow = revenue - opex - capex - tax + credits (+ itc)
    bad = []
    for r in rows:
        exp = (r.get("revenue", 0) - r.get("opex", 0) - r.get("capex", 0) - r.get("tax", 0)
               + r.get("credits", 0) + r.get("itc", 0))
        if abs(exp - r["cash_flow"]) > 1e-6 * max(abs(exp), abs(r["cash_flow"]), 1.0):
            bad.append(f"t={r['t']}: components={exp:.6g} vs cash_flow={r['cash_flow']:.6g}")
    out.append(C.CheckResult("Each year's cash flow foots from its components", "B. tie-out",
                             C.FAIL if bad else C.PASS, None, C.TOL["exact"],
                             "; ".join(bad[:5]) or f"{len(rows)} rows foot"))
    i = fin.get("discount_rate_nominal")
    if i is not None and all("discount_factor" in r for r in rows):
        mid = fin.get("mid_year", False)
        bad = []
        for r in rows:
            tt = r["t"] - 0.5 if (mid and r.get("energy_MWh", 0) > 0) else r["t"]
            exp = 1 / (1 + i) ** tt
            if abs(exp - r["discount_factor"]) > 1e-6 * exp:
                bad.append(f"t={r['t']}: {r['discount_factor']:.6g} vs 1/(1+i)^t={exp:.6g}")
        out.append(C.CheckResult("Discount factors match the stated nominal rate", "B. tie-out",
                                 C.FAIL if bad else C.PASS, None, C.TOL["exact"],
                                 "; ".join(bad[:5]) or "consistent"))
    if "npv_usd" in fin and all("discount_factor" in r for r in rows):
        s = sum(r["cash_flow"] * r["discount_factor"] for r in rows)
        out.append(C.closure("Sum of discounted cash flows = reported NPV", s + 0.0, fin["npv_usd"],
                             C.TOL["exact"], group="B. tie-out") if abs(fin["npv_usd"]) > 1
                   else C.CheckResult("Sum of discounted cash flows = reported NPV", "B. tie-out",
                                      C.PASS if abs(s - fin["npv_usd"]) < 1.0 else C.FAIL,
                                      abs(s - fin["npv_usd"]), 1.0, f"sum={s:.6g}", units="$"))
    out += lcoe_checks(sim)
    return out


def _npv_at_price(rows, i, price_fn, tax_rate, mid=False):
    """NPV with revenue replaced by price_fn(t) * energy, re-taxing the revenue change."""
    total = 0.0
    for r in rows:
        e = r.get("energy_MWh", 0.0)
        new_rev = price_fn(r["t"]) * e
        d_rev = new_rev - r.get("revenue", 0.0)
        cf = r["cash_flow"] + (1 - tax_rate) * d_rev
        tt = r["t"] - 0.5 if (mid and e > 0) else r["t"]
        total += cf / (1 + i) ** tt
    return total


def lcoe_checks(sim):
    """Definitional check (NPV = 0 at price = LCOE) plus signature checks that recognise
    common WRONG LCOE formulas by recomputing them and seeing which one the reported value hits."""
    rows = _table(sim)
    fin = sim.get("finance") or {}
    L = fin.get("lcoe_usd_per_MWh")
    i = fin.get("discount_rate_nominal")
    if L is None or i is None:
        return [C.skip("LCOE definitional check", "B. reconciliation",
                       "needs finance.lcoe_usd_per_MWh and finance.discount_rate_nominal")]
    infl = fin.get("inflation", 0.0)
    tax = fin.get("tax_rate", 0.0)
    basis = fin.get("price_basis", "nominal")   # "real" => price escalates with inflation
    mid = fin.get("mid_year", False)
    pf = (lambda t: L * (1 + infl) ** t) if basis == "real" else (lambda t: L)
    capex = sum(r.get("capex", 0.0) for r in rows) or 1.0
    out = [C.npv_at_lcoe(_npv_at_price(rows, i, pf, tax, mid), capex,
                         name=f"NPV at price = reported LCOE ({basis} basis) is zero", tol=1e-4)]

    # signature checks (pre-tax forms, built from the table's own cost lines)
    def pv(vals, rate):
        return sum(v / (1 + rate) ** r["t"] for v, r in zip(vals, rows))
    costs = [r.get("capex", 0) + r.get("opex", 0) - r.get("credits", 0) - r.get("itc", 0) for r in rows]
    energy = [r.get("energy_MWh", 0.0) for r in rows]
    real = (1 + i) / (1 + infl) - 1
    # correct pre-tax value: PV(nominal costs @ i) / PV(energy) where a real-basis price
    # escalating with inflation makes the energy PV equal to sum E / (1+r_real)^t
    e_rate = real if basis == "real" else i
    right = pv(costs, i) / sum(e / (1 + e_rate) ** r["t"] for e, r in zip(energy, rows))
    candidates = {
        "energy NOT discounted (PV costs / sum of MWh)": pv(costs, i) / sum(energy),
        "nominal cash flows discounted at the REAL rate": pv(costs, real) / sum(
            e / (1 + real) ** r["t"] for e, r in zip(energy, rows)),
        "simple total cost / total energy (no discounting)": sum(costs) / sum(energy),
    }
    hits = [k for k, v in candidates.items() if abs(v - L) <= 1e-3 * abs(L) and abs(v - right) > 1e-3 * abs(right)]
    out.append(C.CheckResult("LCOE does not match a known-wrong formula", "B. reconciliation",
                             C.FAIL if hits else C.PASS, None, 1e-3,
                             ("reported LCOE matches: " + "; ".join(hits)) if hits else
                             "reported LCOE matches none of: " + "; ".join(
                                 f"{k} = {v:.4g}" for k, v in candidates.items())))
    return out


def accounting_checks(sim):
    out = []
    costs = sim.get("costs") or {}
    if "capex_breakdown_usd" in costs and "capex_total_usd" in costs:
        out.append(C.footing(costs["capex_breakdown_usd"], costs["capex_total_usd"],
                             name="Capex breakdown foots to total"))
    rows = _table(sim)
    if rows and "capex_total_usd" in costs:
        infl = _get(sim, "finance", "inflation") or 0.0
        nominal = sum(r.get("capex", 0.0) for r in rows)
        real = sum(r.get("capex", 0.0) / (1 + infl) ** r["t"] for r in rows)
        total = costs["capex_total_usd"]
        if abs(nominal - total) <= 1e-6 * abs(total):
            det, st = "ties out in the table's own (nominal) dollars", C.PASS
        elif abs(real - total) <= 1e-6 * abs(total):
            det, st = (f"ties out after deflating the table at inflation={infl:.4g}: table is "
                       "nominal, capex total is base-year real. Confirm this is intended."), C.PASS
        else:
            det, st = (f"table nominal sum={nominal:.6g}, deflated={real:.6g}, reported total="
                       f"{total:.6g}: capex is missing, double-counted, or escalated at an "
                       "undisclosed rate"), C.FAIL
        out.append(C.CheckResult("Capex in cash-flow table ties to capex total", "B. tie-out", st,
                                 min(abs(nominal - total), abs(real - total)) / abs(total),
                                 1e-6, det))
    carb = sim.get("carbon") or {}
    if "purchased_t" in carb and "stored_t" in carb:
        out.append(C.carbon_ledger(carb["purchased_t"], carb["stored_t"], carb.get("vented_t", 0.0),
                                   carb.get("inventory_change_t", 0.0), carb.get("credited_t")))
    if sim.get("reported") and sim.get("model_outputs"):
        out.append(C.tie_out(sim["reported"], sim["model_outputs"]))
    return out


def run(sim):
    results = []
    for fn in (balance_checks, property_checks, wellbore_checks, turbine_checks,
               cashflow_checks, accounting_checks):
        try:
            results += fn(sim)
        except Exception as exc:   # a crash in a check is itself a finding about the export
            results.append(C.CheckResult(f"{fn.__name__} crashed", "Z. tooling", C.WARN,
                                         detail=f"{type(exc).__name__}: {exc}"))
    return results
