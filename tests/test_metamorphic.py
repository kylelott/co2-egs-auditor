"""Metamorphic tests on the reference model: relations that must hold without a 'right answer'."""

import pytest

from egs_audit import metamorphic as M, reference
from egs_audit import checks as C

BASE = dict(reference.DEFAULTS, sample_years=[1, 30], n_seg=40)


def test_all_costs_x2_doubles_lcoe():
    r = M.scaling(reference.model, dict(BASE), reference.COST_KEYS, 2.0, "lcoe_real", 2.0, tol=1e-9)
    assert r.status == C.PASS, r.detail


def test_more_doublets_same_lcoe_double_power():
    a = reference.model(dict(BASE))
    b = reference.model(dict(BASE, n_doublets=2))
    assert b["lcoe_real"] == pytest.approx(a["lcoe_real"], rel=1e-9)
    assert b["W_net_MW_y1"] == pytest.approx(2 * a["W_net_MW_y1"], rel=1e-12)


def test_lcoe_rises_with_well_cost():
    r = M.monotonic(reference.model, dict(BASE), "well_cost_usd_per_m", [1500, 2500, 3500],
                    "lcoe_real_no_credits", "up")
    assert r.status == C.PASS, r.detail


def test_power_rises_with_reservoir_temperature():
    r = M.monotonic(reference.model, dict(BASE), "T_res_C", [130, 150, 170], "W_net_MW_y1", "up")
    assert r.status == C.PASS, r.detail


def test_grid_convergence_of_net_power():
    r = M.convergence(reference.model, dict(BASE), "n_seg", [20, 40, 80], "W_net_MW_y1", tol=1e-3)
    assert r.status == C.PASS, r.detail


def test_capex_elasticity_close_to_capital_share():
    # d ln LCOE / d ln(plant cost) must equal the plant's share of LCOE, so it must lie in (0, 1)
    e = M.elasticity(reference.model, dict(BASE), "plant_cost_usd_per_kW_gross", "lcoe_real_no_credits")
    assert 0 < e < 1


def test_variance_bridge_reports_contributions():
    a = dict(BASE)
    b = dict(BASE, well_cost_usd_per_m=3000.0, co2_price_usd_per_t=60.0)
    out = M.variance_bridge(reference.model, a, b, "lcoe_real_no_credits",
                            ["well_cost_usd_per_m", "co2_price_usd_per_t"])
    # LCOE is linear in cost inputs, so one-at-a-time contributions add up exactly
    assert abs(out["interaction_residual"]) < 1e-6 * abs(out["total_change"])
