"""Self-contained reference CO2 thermosiphon case (doublet, direct turbine expansion).

Purpose: (1) an end-to-end worked example of every hand-check and balance check;
(2) a known-good model for the toolkit's own tests (including mutation tests that prove the
checks catch injected bugs); (3) a cross-check for a simulator run at the same inputs.

It is a deliberately simple, fully transparent model, NOT a replacement for a reservoir
simulator. Stated simplifications: adiabatic wells, lumped reservoir impedance, prescribed
linear thermal drawdown, single-phase CO2 everywhere (cooler pressure kept above P_crit so no
two-phase states occur), no brine, make-up CO2 enters at cooler-outlet conditions.

Loop: injection wellhead -> injection well (down) -> reservoir (impedance, heating)
      -> production well (up) -> turbine -> cooler -> [optional pump] -> injection wellhead
"""

from __future__ import annotations

import copy

from . import finance, properties as props, turbo, wellbore
from . import checks as C
from .calcsheet import CalcSheet
from .units import C_to_K, G, HOURS_PER_YEAR, MPa_to_Pa

DEFAULTS = {
    # geometry / operation
    "depth_m": 3500.0,
    "well_diameter_m": 0.2,
    "roughness_m": 4.5e-5,
    "n_seg": 100,
    "m_inj_kg_s": 100.0,          # per doublet
    "n_doublets": 1,
    "loss_fraction": 0.01,        # share of injected CO2 lost to the formation (stored)
    "T_res_C": 150.0,             # initial production bottomhole temperature
    "drawdown_K_per_yr": 0.3,     # prescribed linear thermal drawdown of production T
    "reservoir_impedance_MPa_s_kg": 0.02,  # dP_res = R * m_inj
    "P_cooler_MPa": 7.5,          # turbine exhaust / cooler pressure (> P_crit: single phase)
    "T_cooler_out_C": 25.0,
    "pump_dP_MPa": 0.0,           # optional injection pump boost after the cooler
    "eta_turbine": 0.85,
    "eta_pump": 0.80,
    "eta_generator": 0.97,
    "fan_power_fraction": 0.01,   # cooling fan power as a fraction of heat rejected
    "capacity_factor": 0.90,
    "sample_years": [1, 10, 20, 30],   # years evaluated in full; others linearly interpolated
    # costs (real, base-year $)
    "well_cost_usd_per_m": 2500.0,
    "stimulation_usd": 3.0e6,
    "plant_cost_usd_per_kW_gross": 2500.0,
    "co2_price_usd_per_t": 40.0,
    "initial_fill_t": 5.0e5,
    "fixed_om_fraction_of_capex": 0.02,
    "credit_45q_usd_per_t": 85.0,
    "credit_years": 12,
    "credit_initial_fill": False,
    # finance
    "life_years": 30,
    "construction_split": [0.5, 0.5],
    "real_discount_rate": 0.07,
    "inflation": 0.025,
    "tax_rate": 0.21,
    "macrs_class": 5,
}

COST_KEYS = ["well_cost_usd_per_m", "stimulation_usd", "plant_cost_usd_per_kW_gross",
             "co2_price_usd_per_t", "credit_45q_usd_per_t"]


def thermo_year(p, year):
    """Full thermodynamic loop for one doublet in a given operating year."""
    m_i = p["m_inj_kg_s"]
    m_l = m_i * p["loss_fraction"]
    m_p = m_i - m_l
    H = p["depth_m"]
    P_c = MPa_to_Pa(p["P_cooler_MPa"])
    T_c = C_to_K(p["T_cooler_out_C"])
    P_iwh = P_c + MPa_to_Pa(p["pump_dP_MPa"])

    cooler_out = props.state_PT(P_c, T_c)
    if p["pump_dP_MPa"] > 0:
        pump = turbo.compressor(P_c, T_c, P_iwh, p["eta_pump"], m_i)
        T_iwh, W_pump, S_pump = pump.T_out, pump.power, pump.entropy_gen
    else:
        T_iwh, W_pump, S_pump = T_c, 0.0, 0.0

    inj = wellbore.integrate_column(P_iwh, T_iwh, m_i, H, p["well_diameter_m"],
                                    p["roughness_m"], p["n_seg"], "down")
    P_ibh = inj.outlet["P"]
    P_pbh = P_ibh - MPa_to_Pa(p["reservoir_impedance_MPa_s_kg"] * m_i)
    T_pbh = C_to_K(p["T_res_C"]) - p["drawdown_K_per_yr"] * (year - 1)
    prod = wellbore.integrate_column(P_pbh, T_pbh, m_p, H, p["well_diameter_m"],
                                     p["roughness_m"], p["n_seg"], "up")
    P_pwh, T_pwh = prod.outlet["P"], prod.outlet["T"]
    if P_pwh <= P_c:
        raise ValueError(f"no thermosiphon drive: production wellhead {P_pwh / 1e6:.3f} MPa <= "
                         f"cooler {P_c / 1e6:.3f} MPa (needs a circulation pump)")
    turb = turbo.turbine(P_pwh, T_pwh, P_c, p["eta_turbine"], m_p)
    Q_rej = m_p * (turb.h_out - cooler_out.h)
    h_loss = props.state_PT(P_pbh, T_pbh).h          # lost fluid leaves at reservoir state
    Q_res = m_p * prod.inlet["h"] + m_l * h_loss - m_i * inj.outlet["h"]
    W_fan = p["fan_power_fraction"] * Q_rej
    W_gross = p["eta_generator"] * turb.power
    W_net = W_gross - W_fan - W_pump
    S_cooler = m_p * (cooler_out.s - props.s_Ph(P_c, turb.h_out)) + Q_rej / T_c  # >= 0
    return {
        "year": year, "m_inj": m_i, "m_prod": m_p, "m_loss": m_l,
        "P_iwh": P_iwh, "T_iwh": T_iwh, "P_ibh": P_ibh, "T_ibh": inj.outlet["T"],
        "rho_iwh": inj.inlet["rho"], "rho_ibh": inj.outlet["rho"],
        "P_pbh": P_pbh, "T_pbh": T_pbh, "P_pwh": P_pwh, "T_pwh": T_pwh,
        "rho_pbh": prod.inlet["rho"], "rho_pwh": prod.outlet["rho"],
        "h_iwh": inj.inlet["h"], "h_ibh": inj.outlet["h"], "h_pbh": prod.inlet["h"],
        "h_pwh": prod.outlet["h"], "h_turb_out": turb.h_out, "h_cooler_out": cooler_out.h,
        "h_loss": h_loss, "T_turb_out": turb.T_out,
        "inj_dP_grav": inj.dP_gravity, "inj_dP_fric": inj.dP_friction,
        "prod_dP_grav": prod.dP_gravity, "prod_dP_fric": prod.dP_friction,
        "thermosiphon_dP": P_pwh - P_c,
        "Q_res": Q_res, "W_turb": turb.power, "W_pump": W_pump, "W_fan": W_fan,
        "W_gross": W_gross, "W_net": W_net, "Q_rej": Q_rej,
        "S_gen": {"turbine": turb.entropy_gen, "pump": S_pump, "cooler+ambient": S_cooler},
        "s_pbh": props.state_PT(P_pbh, T_pbh).s, "s_pwh": props.state_PT(P_pwh, T_pwh).s,
        "inj_profile": inj, "prod_profile": prod,
    }


def _interp(xs, ys, x):
    if x <= xs[0]:
        return ys[0] + (ys[1] - ys[0]) * (x - xs[0]) / (xs[1] - xs[0])
    for i in range(len(xs) - 1):
        if xs[i] <= x <= xs[i + 1]:
            return ys[i] + (ys[i + 1] - ys[i]) * (x - xs[i]) / (xs[i + 1] - xs[i])
    return ys[-2] + (ys[-1] - ys[-2]) * (x - xs[-2]) / (xs[-1] - xs[-2])


def build_finance(p, W_net_by_year, W_gross_peak, credits=True):
    nd = p["n_doublets"]
    n = p["life_years"]
    secs = HOURS_PER_YEAR * 3600 * p["capacity_factor"]
    energy = [W * nd / 1e6 * HOURS_PER_YEAR * p["capacity_factor"] for W in W_net_by_year]
    wells = 2 * nd * p["depth_m"] * p["well_cost_usd_per_m"]
    stim = nd * p["stimulation_usd"]
    plant = p["plant_cost_usd_per_kW_gross"] * W_gross_peak * nd / 1e3
    fill = nd * p["initial_fill_t"] * p["co2_price_usd_per_t"]
    capex_total = wells + stim + plant + fill
    split = p["construction_split"]
    capex = [capex_total * f for f in split]
    loss_t_per_yr = nd * p["m_inj_kg_s"] * p["loss_fraction"] * secs / 1000.0
    makeup = loss_t_per_yr * p["co2_price_usd_per_t"]
    fom = p["fixed_om_fraction_of_capex"] * capex_total
    cred = [0.0] * n
    if credits:
        for k in range(min(p["credit_years"], n)):
            cred[k] = loss_t_per_yr * p["credit_45q_usd_per_t"]
        if p["credit_initial_fill"]:
            cred[0] += nd * p["initial_fill_t"] * p["credit_45q_usd_per_t"]
    fin = finance.FinanceInputs(
        capex_real_usd=capex, annual_energy_MWh=energy,
        real_discount_rate=p["real_discount_rate"], inflation=p["inflation"],
        fixed_om_real_usd=fom, other_costs_real_usd=makeup, credits_real_usd=cred,
        tax_rate=p["tax_rate"],
        depreciation_schedule=finance.MACRS[p["macrs_class"]] if p["tax_rate"] > 0 else [],
        depreciable_fraction=(wells + stim + plant) / capex_total)  # CO2 fill not depreciable
    breakdown = {"wells": wells, "stimulation": stim, "plant": plant, "initial_CO2_fill": fill}
    return fin, breakdown, {"loss_t_per_yr": loss_t_per_yr, "makeup_usd_per_yr": makeup,
                            "fixed_om_usd_per_yr": fom, "capex_total": capex_total}


def run(params=None):
    p = copy.deepcopy(DEFAULTS)
    p.update(params or {})
    years = sorted(set(p["sample_years"]))
    thermo = {y: thermo_year(p, y) for y in years}
    W_net_s = [thermo[y]["W_net"] for y in years]
    W_net_by_year = [_interp(years, W_net_s, y) for y in range(1, p["life_years"] + 1)]
    W_gross_peak = max(t["W_gross"] for t in thermo.values())
    fin, breakdown, extras = build_finance(p, W_net_by_year, W_gross_peak, credits=True)
    res = finance.solve(fin)
    fin_nc, _, _ = build_finance(p, W_net_by_year, W_gross_peak, credits=False)
    res_nc = finance.solve(fin_nc)
    return {"params": p, "thermo": thermo, "W_net_by_year": W_net_by_year,
            "finance_inputs": fin, "finance": res, "finance_no_credits": res_nc,
            "capex_breakdown": breakdown, **extras}


def model(params):
    """Callable for metamorphic tests: inputs dict -> headline outputs dict."""
    r = run(params)
    t1 = r["thermo"][min(r["thermo"])]
    return {"lcoe_real": r["finance"].lcoe_real,
            "lcoe_real_no_credits": r["finance_no_credits"].lcoe_real,
            "W_net_MW_y1": t1["W_net"] * r["params"]["n_doublets"] / 1e6,
            "capex_total": r["capex_total"]}


# ------------------------------------------------------------------ checks & calc sheet

def balance_checks(r):
    out = []
    p = r["params"]
    for y, t in r["thermo"].items():
        lhs = t["Q_res"] + t["W_pump"] + t["m_loss"] * t["h_cooler_out"]
        rhs = t["W_turb"] + t["Q_rej"] + t["m_loss"] * (t["h_loss"] - G * p["depth_m"])
        out.append(C.closure(f"Energy balance, year {y} (incl. lost/make-up streams)", lhs, rhs,
                             C.TOL["balance"], detail=f"in={lhs:.6g} W, out={rhs:.6g} W"))
        out.append(C.mass_balance(t["m_inj"], t["m_prod"], t["m_loss"],
                                  name=f"Mass balance, year {y}", tol=C.TOL["exact"]))
        segs = {"injection well": t["P_ibh"] - t["P_iwh"],
                "reservoir": t["P_pbh"] - t["P_ibh"],
                "production well": t["P_pwh"] - t["P_pbh"],
                "turbine": MPa_to_Pa(p["P_cooler_MPa"]) - t["P_pwh"],
                "pump": MPa_to_Pa(p["pump_dP_MPa"])}
        out.append(C.pressure_loop(segs, name=f"Pressure loop, year {y}"))
        out.append(C.entropy_generation(t["S_gen"], name=f"Entropy generation, year {y}"))
        out.append(C.carnot_bound(t["W_net"], t["Q_res"], t["T_pbh"],
                                  C_to_K(p["T_cooler_out_C"]), name=f"Carnot bound, year {y}"))
        dead = props.state_PT(101325.0, C_to_K(p["T_cooler_out_C"]))
        out.append(C.exergy_bound(t["W_net"], t["m_prod"], t["h_pwh"], t["s_pwh"], dead.h,
                                  dead.s, dead.T, name=f"Exergy bound at wellhead, year {y}"))
        out.append(C.positivity({"rho_inj": t["inj_profile"].rho, "rho_prod": t["prod_profile"].rho,
                                 "P_inj": t["inj_profile"].P, "P_prod": t["prod_profile"].P,
                                 "W_net": t["W_net"]}, name=f"Positivity, year {y}"))
    f = r["finance"]
    out.append(C.npv_at_lcoe(f.npv_at_lcoe, r["capex_total"]))
    out.append(C.footing(r["capex_breakdown"], r["capex_total"], name="Capex breakdown foots"))
    rows = f.table
    dep_total = sum(x["depreciation"] for x in rows)
    fin = r["finance_inputs"]
    capex_nom = sum(c * (1 + fin.inflation) ** t for t, c in enumerate(fin.capex_real_usd))
    out.append(C.two_path("Accumulated depreciation = depreciable basis", dep_total,
                          fin.depreciable_fraction * capex_nom - fin.itc_basis_reduction *
                          fin.itc_rate * capex_nom))
    stored = r["loss_t_per_yr"] * p["life_years"]
    credited = r["loss_t_per_yr"] * min(p["credit_years"], p["life_years"])
    out.append(C.carbon_ledger(stored, stored, credited_t=credited,
                               name="Carbon ledger (make-up purchased = stored; credited <= stored)"))
    return out


def calc_sheet(r, year=None) -> CalcSheet:
    """Independent step-by-step chain for one year: what a reviewer checks by hand."""
    p = r["params"]
    year = year or min(r["thermo"])
    t = r["thermo"][year]
    H = p["depth_m"]
    cs = CalcSheet("CO2 thermosiphon reference case", f"year {year}, depth {H:.0f} m, "
                   f"m_inj {p['m_inj_kg_s']} kg/s per doublet, T_res {p['T_res_C']} C")
    cs.add("1", "Injection wellhead density", "rho = rho(P_iwh, T_iwh) [Span-Wagner]",
           t["rho_iwh"], "kg/m3", "CoolProp CO2 (Span & Wagner 1996)",
           {"P_iwh": (t["P_iwh"] / 1e6, "MPa"), "T_iwh": (t["T_iwh"] - 273.15, "C")},
           tol_class="property")
    rho_avg_i = 0.5 * (t["rho_iwh"] + t["rho_ibh"])
    cs.add("2a", "Injection column head (estimate)", "dP ~ rho_avg g H", rho_avg_i * G * H / 1e6,
           "MPa", "hydrostatics", {"rho_avg": (rho_avg_i, "kg/m3"), "H": (H, "m")},
           tol_class="estimate", note="back-of-envelope; compare with 2b")
    cs.add("2b", "Injection column head (integrated)", "dP_grav = integral rho g dz",
           t["inj_dP_grav"] / 1e6, "MPa", "wellbore.integrate_column", tol_class="discretized")
    cs.add("3", "Injection friction loss", "integral f rho v^2/(2D) dz (Colebrook)",
           t["inj_dP_fric"] / 1e6, "MPa", "Darcy-Weisbach + Colebrook-White",
           {"D": (p["well_diameter_m"], "m"), "eps": (p["roughness_m"], "m")},
           tol_class="discretized")
    cs.add("4", "Injection bottomhole pressure", "P_ibh = P_iwh + dP_grav - dP_fric",
           t["P_ibh"] / 1e6, "MPa", tol_class="discretized")
    cs.add("5", "Injection bottomhole enthalpy", "h_ibh = h_iwh + g H (adiabatic)",
           (t["h_iwh"] + G * H) / 1e3, "kJ/kg", "steady energy eq., KE neglected",
           {"h_iwh": (t["h_iwh"] / 1e3, "kJ/kg"), "gH": (G * H / 1e3, "kJ/kg")})
    cs.add("6", "Production bottomhole pressure", "P_pbh = P_ibh - R m_inj",
           t["P_pbh"] / 1e6, "MPa", "lumped reservoir impedance",
           {"R": (p["reservoir_impedance_MPa_s_kg"], "MPa s/kg"), "m_inj": (t["m_inj"], "kg/s")},
           tol_class="discretized")
    cs.add("7", "Production bottomhole temperature", "T_pbh = T_res - drawdown (year-1)",
           t["T_pbh"] - 273.15, "C", tol_class="exact")
    rho_avg_p = 0.5 * (t["rho_pbh"] + t["rho_pwh"])
    cs.add("8a", "Production column head (estimate)", "dP ~ rho_avg g H", rho_avg_p * G * H / 1e6,
           "MPa", "hydrostatics", tol_class="estimate")
    cs.add("8b", "Production column head (integrated)", "integral rho g dz",
           t["prod_dP_grav"] / 1e6, "MPa", tol_class="discretized")
    cs.add("9", "Production wellhead pressure", "P_pwh = P_pbh - dP_grav - dP_fric",
           t["P_pwh"] / 1e6, "MPa", tol_class="discretized")
    cs.add("10", "Thermosiphon drive", "P_pwh - P_cooler (available for the turbine)",
           (t["P_pwh"] - MPa_to_Pa(p["P_cooler_MPa"])) / 1e6, "MPa", tol_class="discretized",
           note="positive => circulation without a pump")
    cs.add("11", "Production wellhead enthalpy", "h_pwh = h_pbh - g H", t["h_pwh"] / 1e3, "kJ/kg",
           tol_class="property")
    cs.add("12", "Turbine power", "W = m_p eta (h_pwh - h_s(P_c, s_pwh))", t["W_turb"] / 1e6, "MW",
           "isentropic efficiency, expansion", {"eta": (p["eta_turbine"], "-"),
                                                "m_p": (t["m_prod"], "kg/s")},
           tol_class="property")
    cs.add("13", "Heat rejected", "Q_rej = m_p (h_turb_out - h_cooler_out)", t["Q_rej"] / 1e6, "MW",
           tol_class="property")
    cs.add("14", "Reservoir heat extraction", "Q_res = m_p h_pbh + m_l h_loss - m_i h_ibh",
           t["Q_res"] / 1e6, "MW", tol_class="property")
    cs.add("15", "Net power", "W_net = eta_gen W_turb - W_fan - W_pump", t["W_net"] / 1e6, "MW",
           inputs={"eta_gen": (p["eta_generator"], "-"), "W_fan": (t["W_fan"] / 1e6, "MW"),
                   "W_pump": (t["W_pump"] / 1e6, "MW")}, tol_class="property")
    eta_c = 1 - C_to_K(p["T_cooler_out_C"]) / t["T_pbh"]
    cs.add("16", "Net efficiency vs Carnot", "eta_net / eta_Carnot", (t["W_net"] / t["Q_res"]) / eta_c,
           "-", "2nd law", tol_class="estimate", note="must be < 1")
    f = r["finance"]
    e1 = r["finance_inputs"].annual_energy_MWh[0]
    cs.add("17", "Year-1 net energy", "E = W_net n_doublets 8760 CF", e1, "MWh",
           inputs={"CF": (p["capacity_factor"], "-")})
    cs.add("18", "Total capex", "wells + stimulation + plant + CO2 fill", r["capex_total"] / 1e6,
           "M$", inputs={k: (v / 1e6, "M$") for k, v in r["capex_breakdown"].items()})
    cs.add("19", "CRF (real)", "r(1+r)^n/((1+r)^n-1)",
           finance.crf(p["real_discount_rate"], p["life_years"]), "1/yr")
    cs.add("20", "Real LCOE (after tax, with credits)", "price s.t. NPV = 0", f.lcoe_real, "$/MWh",
           "finance.solve")
    cs.add("21", "Real LCOE (no credits)", "price s.t. NPV = 0, credits = 0",
           r["finance_no_credits"].lcoe_real, "$/MWh", "finance.solve")
    cs.add("22", "Pre-tax real LCOE (independent ratio)", "PV(costs - credits)/PV(energy) @ r_real",
           f.simple_pretax_lcoe_real, "$/MWh", "closed form, no cash-flow table",
           note="differs from 20 only by taxes/depreciation; a large gap -> check tax treatment")
    return cs


def to_export(r, year=None):
    """The reference run in the adapter's JSON schema (the documented example export)."""
    p = r["params"]
    year = year or min(r["thermo"])
    t = r["thermo"][year]
    f = r["finance"]
    fin = r["finance_inputs"]

    def state(P, T, h, rho=None):
        d = {"P_Pa": P, "T_K": T, "h_J_kg": h}
        if rho is not None:
            d["rho_kg_m3"] = rho
        return d

    P_c = MPa_to_Pa(p["P_cooler_MPa"])
    rows = [{k: row[k] for k in ("t", "energy_MWh", "revenue", "capex", "opex", "tax",
                                 "credits", "itc", "cash_flow", "discount_factor")}
            for row in f.table]
    nd = p["n_doublets"]
    stored = r["loss_t_per_yr"] * p["life_years"]
    return {
        "meta": {"simulator": "egs_audit reference case", "case": f"year {year}",
                 "note": "per-doublet thermodynamics; finance for the whole project"},
        "depth_m": p["depth_m"],
        "T_ambient_K": C_to_K(p["T_cooler_out_C"]),
        "wells": {"diameter_m": p["well_diameter_m"], "roughness_m": p["roughness_m"]},
        "equipment": {"eta_turbine": p["eta_turbine"], "eta_generator": p["eta_generator"]},
        "flows": {"m_inj_kg_s": t["m_inj"], "m_prod_kg_s": t["m_prod"], "m_loss_kg_s": t["m_loss"]},
        "states": {
            "inj_wellhead": state(t["P_iwh"], t["T_iwh"], t["h_iwh"], t["rho_iwh"]),
            "inj_bottomhole": state(t["P_ibh"], t["T_ibh"], t["h_ibh"], t["rho_ibh"]),
            "prod_bottomhole": state(t["P_pbh"], t["T_pbh"], t["h_pbh"], t["rho_pbh"]),
            "prod_wellhead": state(t["P_pwh"], t["T_pwh"], t["h_pwh"], t["rho_pwh"]),
            "turbine_out": state(P_c, t["T_turb_out"], t["h_turb_out"]),
        },
        "powers_W": {
            # reservoir heat here is defined for the loop control volume incl. lost/make-up
            # streams, so the simple energy_balance form closes
            "Q_reservoir": t["Q_res"] + t["m_loss"] * (t["h_cooler_out"] - t["h_loss"] + G * p["depth_m"]),
            "W_turbine": t["W_turb"], "W_pumps": t["W_pump"], "W_fans": t["W_fan"],
            "Q_rejected": t["Q_rej"], "W_gross": t["W_gross"], "W_net": t["W_net"],
        },
        "pressure_segments_Pa": {
            "injection well": t["P_ibh"] - t["P_iwh"], "reservoir": t["P_pbh"] - t["P_ibh"],
            "production well": t["P_pwh"] - t["P_pbh"], "turbine": P_c - t["P_pwh"],
            "pump": MPa_to_Pa(p["pump_dP_MPa"]),
        },
        "entropy_generation_W_K": t["S_gen"],
        "costs": {"capex_breakdown_usd": r["capex_breakdown"], "capex_total_usd": r["capex_total"]},
        "cash_flow_table": rows,
        "finance": {"discount_rate_nominal": f.nominal_rate, "inflation": fin.inflation,
                    "tax_rate": fin.tax_rate, "price_basis": "real", "mid_year": fin.mid_year,
                    "lcoe_usd_per_MWh": f.lcoe_real, "npv_usd": f.npv_at_lcoe},
        "carbon": {"purchased_t": stored, "stored_t": stored, "vented_t": 0.0,
                   "credited_t": r["loss_t_per_yr"] * min(p["credit_years"], p["life_years"])},
        "reported": {"lcoe_usd_per_MWh": f.lcoe_real, "W_net_MW": t["W_net"] * nd / 1e6},
        "model_outputs": {"lcoe_usd_per_MWh": f.lcoe_real, "W_net_MW": t["W_net"] * nd / 1e6},
    }
