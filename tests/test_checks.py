"""The checks pass on a correct model AND catch deliberately injected bugs (mutation tests).

A check that never fails is worthless; every test below plants a specific, realistic bug.
"""

import copy
import json
import os

import pytest

from egs_audit import adapter, finance, metamorphic as M, reference
from egs_audit import checks as C
from egs_audit.units import MPa_to_Pa

FAST = {"sample_years": [1, 30], "n_seg": 50}


@pytest.fixture(scope="module")
def ref():
    return reference.run(FAST)


@pytest.fixture(scope="module")
def export(ref):
    return reference.to_export(ref)


def _status(results, name_part):
    return [r.status for r in results if name_part in r.name]


def test_reference_all_pass(ref):
    res = reference.balance_checks(ref)
    assert all(r.status == C.PASS for r in res), [r for r in res if r.status != C.PASS]


def test_example_export_all_pass(export):
    res = adapter.run(export)
    bad = [r for r in res if r.status in (C.FAIL, C.WARN)]
    assert not bad, bad


def test_committed_example_json_passes():
    path = os.path.join(os.path.dirname(__file__), "..", "examples", "simulator_outputs.example.json")
    res = adapter.run(adapter.load(path))
    assert not [r for r in res if r.status == C.FAIL]


# ---------------------------------------------------------------- mutations: physics

def test_catches_missing_heat_rejection_term(export):
    sim = copy.deepcopy(export)
    sim["powers_W"]["Q_rejected"] *= 0.9           # e.g. cooler duty computed on wrong mass flow
    assert _status(adapter.run(sim), "Energy balance") == [C.FAIL]


def test_catches_unaccounted_parasitic(export):
    sim = copy.deepcopy(export)
    sim["powers_W"]["W_net"] = sim["powers_W"]["W_gross"]   # fan power forgotten
    assert _status(adapter.run(sim), "Net power = gross") == [C.FAIL]


def test_catches_mass_leak(export):
    sim = copy.deepcopy(export)
    sim["flows"]["m_loss_kg_s"] = 0.0              # loss not tracked
    assert _status(adapter.run(sim), "Mass balance") == [C.FAIL]


def test_catches_missing_reservoir_pressure_drop(export):
    sim = copy.deepcopy(export)
    sim["pressure_segments_Pa"]["reservoir"] = 0.0
    assert _status(adapter.run(sim), "Pressure loop") == [C.FAIL]


def test_catches_bad_density(export):
    sim = copy.deepcopy(export)
    sim["states"]["inj_wellhead"]["rho_kg_m3"] *= 1.05   # e.g. cubic EOS near critical point
    assert C.FAIL in _status(adapter.run(sim), "Density at 'inj_wellhead'")


def test_catches_wellbore_gravity_sign_error(export):
    sim = copy.deepcopy(export)
    st = sim["states"]
    st["inj_bottomhole"]["P_Pa"] = 2 * st["inj_wellhead"]["P_Pa"] - st["inj_bottomhole"]["P_Pa"]
    assert _status(adapter.run(sim), "injection well outlet pressure") == [C.FAIL]


def test_catches_thermosiphon_from_endpoint_density(ref):
    # a simulator using wellhead density for the whole column gets the head badly wrong
    t = ref["thermo"][1]
    endpoint = t["rho_iwh"] * 9.80665 * ref["params"]["depth_m"]
    r = C.closure("column head", endpoint, t["inj_dP_grav"], C.TOL["discretized"])
    assert r.status == C.FAIL


def test_catches_turbine_efficiency_bug(export):
    sim = copy.deepcopy(export)
    sim["powers_W"]["W_turbine"] /= 0.85           # efficiency applied as divide
    assert _status(adapter.run(sim), "Turbine power") == [C.FAIL]


def test_entropy_catches_compressor_eta_wrong_direction():
    from egs_audit import properties as P
    P_in, T_in, P_out, eta = MPa_to_Pa(7.5), 298.15, MPa_to_Pa(12), 0.8
    st = P.state_PT(P_in, T_in)
    h_s = P.h_Ps(P_out, st.s)
    h_bug = st.h + eta * (h_s - st.h)              # BUG: multiply instead of divide
    s_gen = 100 * (P.s_Ph(P_out, h_bug) - st.s)
    assert C.entropy_generation({"compressor": s_gen}).status == C.FAIL


def test_carnot_catches_impossible_efficiency():
    assert C.carnot_bound(5e6, 1e7, 400.0, 300.0).status == C.FAIL


# ---------------------------------------------------------------- mutations: finance

def test_catches_undiscounted_energy_lcoe(export):
    sim = copy.deepcopy(export)
    rows = sim["cash_flow_table"]
    i = sim["finance"]["discount_rate_nominal"]
    pv_costs = sum((r["capex"] + r["opex"] - r["credits"]) / (1 + i) ** r["t"] for r in rows)
    sim["finance"]["lcoe_usd_per_MWh"] = pv_costs / sum(r["energy_MWh"] for r in rows)
    res = adapter.run(sim)
    assert _status(res, "known-wrong formula") == [C.FAIL]
    assert _status(res, "NPV at price") == [C.FAIL]


def test_catches_real_rate_on_nominal_flows(export):
    sim = copy.deepcopy(export)
    rows = sim["cash_flow_table"]
    i, pi = sim["finance"]["discount_rate_nominal"], sim["finance"]["inflation"]
    r_ = (1 + i) / (1 + pi) - 1
    pv = lambda xs: sum(x / (1 + r_) ** r["t"] for x, r in zip(xs, rows))
    sim["finance"]["lcoe_usd_per_MWh"] = pv([r["capex"] + r["opex"] - r["credits"] for r in rows]) / \
        pv([r["energy_MWh"] for r in rows])
    assert _status(adapter.run(sim), "known-wrong formula") == [C.FAIL]


def test_catches_cash_flow_row_error(export):
    sim = copy.deepcopy(export)
    sim["cash_flow_table"][5]["cash_flow"] += 1e5  # stale pasted number
    assert _status(adapter.run(sim), "foots from its components") == [C.FAIL]


def test_catches_wrong_discount_factor(export):
    sim = copy.deepcopy(export)
    sim["cash_flow_table"][10]["discount_factor"] *= 1.01
    assert _status(adapter.run(sim), "Discount factors") == [C.FAIL]


def test_catches_capex_not_footing(export):
    sim = copy.deepcopy(export)
    sim["costs"]["capex_breakdown_usd"]["stimulation"] = 0.0
    assert _status(adapter.run(sim), "Capex breakdown") == [C.FAIL]


def test_catches_over_credited_co2(export):
    sim = copy.deepcopy(export)
    sim["carbon"]["credited_t"] = sim["carbon"]["stored_t"] * 1.5
    assert _status(adapter.run(sim), "Carbon ledger") == [C.FAIL]


def test_catches_reported_number_not_tied_out(export):
    sim = copy.deepcopy(export)
    sim["reported"]["lcoe_usd_per_MWh"] *= 0.9
    sim["reported"]["capacity_MW"] = 5.0           # untraceable number
    r = [x for x in adapter.run(sim) if x.name.startswith("Tie-out")][0]
    assert r.status == C.FAIL and "untraceable" in r.detail


def test_roll_forward_and_cross_footing():
    assert C.roll_forward([0, 10], [10, 5], [0, 2], [10, 13]).status == C.PASS
    assert C.roll_forward([0, 10], [10, 5], [0, 2], [10, 14]).status == C.FAIL
    m = [[1, 2], [3, 4]]
    assert C.cross_footing(m, [3, 7], [4, 6], 10).status == C.PASS
    assert C.cross_footing(m, [3, 7], [4, 6], 11).status == C.FAIL


def test_kink_detector():
    xs = [i * 0.1 for i in range(-20, 21)]
    assert M.kinks(xs, [abs(x) for x in xs]).status == C.WARN
    assert M.kinks(xs, [x * x for x in xs]).status == C.PASS


def test_exported_json_is_serialisable(export):
    json.dumps(export)
