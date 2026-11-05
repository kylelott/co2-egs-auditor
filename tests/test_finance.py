"""Finance engine vs hand-worked examples and identities."""

import pytest

from egs_audit import finance as F


def test_crf_hand_value():
    # 0.07, 30 yr: 0.07*1.07^30/(1.07^30-1) = 0.0805864
    assert F.crf(0.07, 30) == pytest.approx(0.0805864, rel=1e-6)
    assert F.crf(0.0, 20) == pytest.approx(1 / 20)


def test_fisher_not_additive():
    assert F.nominal_rate(0.07, 0.025) == pytest.approx(0.09675)
    assert F.real_rate(F.nominal_rate(0.05, 0.03), 0.03) == pytest.approx(0.05)


def test_two_year_hand_example():
    # capex 1000 at t=0, 10 MWh in years 1 and 2, r = 10 %, no tax/inflation
    # PV(E) = 10/1.1 + 10/1.21 = 17.355372; LCOE = 1000/17.355372 = 57.619048
    inp = F.FinanceInputs([1000.0], [10.0, 10.0], 0.10)
    r = F.solve(inp)
    assert r.lcoe_real == pytest.approx(57.619048, rel=1e-7)
    # reconciliation: CRF shortcut is valid here (constant output, capex at t=0)
    assert r.lcoe_real == pytest.approx(F.simple_lcoe(1000, 0.10, 2, 0, 10), rel=1e-12)


def test_tax_hand_example():
    # capex 1000 at t=0, one year of 10 MWh, 50 % tax, 100 % depreciation in year 1, r = 10 %
    # NPV = -1000 + (10p - 0.5(10p - 1000))/1.1 = 0  ->  p = 120 ; pre-tax would be 110
    inp = F.FinanceInputs([1000.0], [10.0], 0.10, tax_rate=0.5, depreciation_schedule=[1.0])
    r = F.solve(inp)
    assert r.lcoe_real == pytest.approx(120.0, rel=1e-10)
    assert r.simple_pretax_lcoe_real == pytest.approx(110.0, rel=1e-10)


def _base(**kw):
    d = dict(capex_real_usd=[5e7, 5e7], annual_energy_MWh=[1e5] * 30, real_discount_rate=0.07,
             fixed_om_real_usd=2e6, variable_om_real_usd_per_MWh=3.0, other_costs_real_usd=5e5)
    d.update(kw)
    return F.FinanceInputs(**d)


def test_npv_zero_at_lcoe_and_irr_equals_rate():
    inp = _base(inflation=0.025, tax_rate=0.21, depreciation_schedule=F.MACRS[5],
                credits_real_usd=[1e6] * 12 + [0.0] * 18)
    r = F.solve(inp)
    assert abs(r.npv_at_lcoe) < 1e-4
    cfs = [row["cash_flow"] for row in r.table]
    assert F.irr(cfs) == pytest.approx(r.nominal_rate, abs=1e-8)


def test_no_tax_real_lcoe_independent_of_inflation():
    a = F.solve(_base(inflation=0.0)).lcoe_real
    b = F.solve(_base(inflation=0.04)).lcoe_real
    assert a == pytest.approx(b, rel=1e-10)


def test_no_tax_matches_independent_pretax_ratio():
    r = F.solve(_base(inflation=0.03))
    assert r.lcoe_real == pytest.approx(r.simple_pretax_lcoe_real, rel=1e-10)


def test_with_tax_inflation_raises_real_lcoe():
    # depreciation is not indexed, so inflation erodes the tax shield
    kw = dict(tax_rate=0.21, depreciation_schedule=F.MACRS[5])
    assert F.solve(_base(inflation=0.04, **kw)).lcoe_real > F.solve(_base(inflation=0.0, **kw)).lcoe_real


def test_nominal_levelized_exceeds_real_with_inflation():
    r = F.solve(_base(inflation=0.025))
    assert r.lcoe_nominal_levelized > r.lcoe_real


def test_zero_discount_is_simple_ratio():
    inp = _base(real_discount_rate=0.0)
    r = F.solve(inp)
    total = 1e8 + 30 * (2e6 + 3.0 * 1e5 + 5e5)
    assert r.lcoe_real == pytest.approx(total / 3e6, rel=1e-12)


def test_scaling_all_costs_scales_lcoe():
    kw = dict(tax_rate=0.21, depreciation_schedule=F.MACRS[5], inflation=0.02)
    a = F.solve(_base(**kw)).lcoe_real
    b = F.solve(_base(capex_real_usd=[1e8, 1e8], fixed_om_real_usd=4e6,
                      variable_om_real_usd_per_MWh=6.0, other_costs_real_usd=1e6, **kw)).lcoe_real
    assert b == pytest.approx(2 * a, rel=1e-10)


def test_mid_year_lowers_lcoe():
    assert F.solve(_base(mid_year=True)).lcoe_real < F.solve(_base()).lcoe_real


def test_unindexed_credits_worth_less():
    kw = dict(inflation=0.03, credits_real_usd=[2e6] * 12 + [0.0] * 18)
    assert F.solve(_base(credits_escalate=False, **kw)).lcoe_real > F.solve(_base(**kw)).lcoe_real


def test_drawdown_raises_lcoe():
    flat = F.solve(_base()).lcoe_real
    decl = F.solve(_base(annual_energy_MWh=[1e5 * (1 - 0.01 * k) for k in range(30)])).lcoe_real
    assert decl > flat


@pytest.mark.parametrize("cls", sorted(F.MACRS))
def test_macrs_sums_to_one(cls):
    assert sum(F.MACRS[cls]) == pytest.approx(1.0, abs=1e-3)


def test_tax_without_depreciation_is_rejected():
    with pytest.raises(ValueError):
        F.solve(_base(tax_rate=0.21))


def test_losses_not_usable_still_definitional():
    inp = _base(tax_rate=0.21, depreciation_schedule=F.MACRS[5], tax_losses_usable=False)
    r = F.solve(inp)
    assert abs(r.npv_at_lcoe) / 1e8 < 1e-6
    usable = F.solve(_base(tax_rate=0.21, depreciation_schedule=F.MACRS[5])).lcoe_real
    assert r.lcoe_real >= usable - 1e-9
