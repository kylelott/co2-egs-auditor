"""Properties, wellbore and turbomachinery vs limiting cases and identities."""

import pytest

from egs_audit import properties as P
from egs_audit import turbo, wellbore
from egs_audit.units import G, MPa_to_Pa, C_to_K


def test_critical_constants():
    assert P.T_CRIT == pytest.approx(304.13, abs=0.01)
    assert P.P_CRIT == pytest.approx(7.3773e6, rel=1e-4)


def test_ideal_gas_limit_low_pressure():
    T, p = 400.0, 1e5
    assert P.state_PT(p, T).rho == pytest.approx(P.ideal_gas_density(p, T), rel=0.01)


def test_two_phase_and_range_guards():
    with pytest.raises(P.PropertyRangeError):
        P.state_PT(1e5, 100.0)            # below triple point
    with pytest.raises(P.PropertyRangeError):
        P.P_sat(C_to_K(35.0))             # CO2 cannot condense above T_crit


def test_near_critical_flag():
    assert P.is_near_critical(7.5e6, C_to_K(30))
    assert not P.is_near_critical(20e6, C_to_K(150))


@pytest.mark.parametrize("Re", [1e4, 1e5, 1e6, 1e7])
def test_haaland_close_to_colebrook(Re):
    a = wellbore.friction_factor_haaland(Re, 2e-4)
    b = wellbore.friction_factor_colebrook(Re, 2e-4)
    assert a == pytest.approx(b, rel=0.03)


def _inj(**kw):
    d = dict(P_in=MPa_to_Pa(7.5), T_in=C_to_K(25), m_dot=100.0, depth=3000.0, D=0.2, n_seg=100)
    d.update(kw)
    return wellbore.integrate_column(**d)


def test_enthalpy_rises_by_gH_exactly():
    r = _inj()
    assert r.outlet["h"] - r.inlet["h"] == pytest.approx(G * 3000.0, rel=1e-12)


def test_pressure_decomposition():
    r = _inj()
    assert r.outlet["P"] - r.inlet["P"] == pytest.approx(r.dP_gravity - r.dP_friction, rel=1e-9)


def test_no_friction_is_hydrostatic_and_friction_lowers_bhp():
    nf = _inj(friction=False)
    wf = _inj()
    assert nf.dP_friction == 0.0
    assert wf.outlet["P"] < nf.outlet["P"]


def test_backofenvelope_column_head():
    r = _inj()
    est = wellbore.hydrostatic_estimate(0.5 * (r.rho[0] + r.rho[-1]), 3000.0)
    assert r.dP_gravity == pytest.approx(est, rel=0.05)


def test_wellbore_grid_convergence():
    coarse, fine = _inj(n_seg=25), _inj(n_seg=400)
    assert coarse.outlet["P"] == pytest.approx(fine.outlet["P"], rel=1e-4)


def test_production_friction_adds_loss():
    up = dict(P_in=MPa_to_Pa(30), T_in=C_to_K(150), m_dot=100.0, depth=3000.0, D=0.2,
              direction="up", n_seg=100)
    assert wellbore.integrate_column(**up).outlet["P"] < \
        wellbore.integrate_column(friction=False, **up).outlet["P"]


def test_turbine_isentropic_limit_and_irreversibility():
    ideal = turbo.turbine(MPa_to_Pa(14), C_to_K(90), MPa_to_Pa(7.5), 1.0, 100.0)
    real = turbo.turbine(MPa_to_Pa(14), C_to_K(90), MPa_to_Pa(7.5), 0.85, 100.0)
    assert abs(ideal.entropy_gen) < 1e-3
    assert real.entropy_gen > 0
    assert real.power == pytest.approx(0.85 * ideal.power, rel=1e-9)


def test_compressor_work_exceeds_isentropic():
    c = turbo.compressor(MPa_to_Pa(7.5), C_to_K(25), MPa_to_Pa(10), 0.8, 100.0)
    assert c.work_specific == pytest.approx((c.h_out_s - c.h_in) / 0.8)
    assert c.entropy_gen > 0
