"""CO2 thermophysical properties via CoolProp (Span-Wagner EOS for CO2).

This is the *independent reference* the simulator's own property calls are compared against.
Every call is range-guarded: out-of-range or two-phase states raise instead of extrapolating.
"""

from __future__ import annotations

from dataclasses import dataclass

import CoolProp.CoolProp as CP

FLUID = "CO2"
T_CRIT = CP.PropsSI("Tcrit", FLUID)      # K   (~304.13)
P_CRIT = CP.PropsSI("pcrit", FLUID)      # Pa  (~7.377e6)
RHO_CRIT = CP.PropsSI("rhocrit", FLUID)  # kg/m3 (~467.6)
T_TRIPLE = CP.PropsSI("Ttriple", FLUID)  # K   (~216.59)
T_MAX = CP.PropsSI("Tmax", FLUID)        # K
P_MAX = CP.PropsSI("pmax", FLUID)        # Pa
M_MOLAR = CP.PropsSI("molar_mass", FLUID)  # kg/mol

# Within this band (relative distance from the critical point) properties change steeply;
# simulators using tables or cubic EOSs typically fail here.
NEAR_CRITICAL_BAND = 0.05


class PropertyRangeError(ValueError):
    pass


@dataclass(frozen=True)
class State:
    P: float     # Pa
    T: float     # K
    rho: float   # kg/m3
    h: float     # J/kg
    s: float     # J/kg/K
    mu: float    # Pa s
    cp: float    # J/kg/K
    phase: str

    def as_dict(self):
        return self.__dict__.copy()


def _guard_PT(P, T):
    if not (T_TRIPLE <= T <= T_MAX):
        raise PropertyRangeError(f"T={T:.2f} K outside CO2 EOS range [{T_TRIPLE:.1f}, {T_MAX:.1f}] K")
    if not (0 < P <= P_MAX):
        raise PropertyRangeError(f"P={P:.3e} Pa outside CO2 EOS range (0, {P_MAX:.3e}] Pa")


def phase_PT(P, T) -> str:
    return CP.PhaseSI("P", P, "T", T, FLUID)


def is_near_critical(P, T, band=NEAR_CRITICAL_BAND) -> bool:
    return abs(P / P_CRIT - 1) < band and abs(T / T_CRIT - 1) < band


_AS = CP.AbstractState("HEOS", FLUID)
_INPUTS = {("P", "T"): CP.PT_INPUTS, ("P", "H"): CP.HmassP_INPUTS}


def _phase_name(code):
    return {CP.iphase_liquid: "liquid", CP.iphase_gas: "gas", CP.iphase_twophase: "twophase",
            CP.iphase_supercritical: "supercritical",
            CP.iphase_supercritical_gas: "supercritical_gas",
            CP.iphase_supercritical_liquid: "supercritical_liquid"}.get(code, "unknown")


def _state(name1, v1, name2, v2) -> State:
    """Evaluate a full state with CoolProp's low-level AbstractState (same EOS as PropsSI)."""
    key = _INPUTS[(name1, name2)]
    try:
        if key == CP.HmassP_INPUTS:
            _AS.update(key, v2, v1)   # CoolProp expects (h, P) order
        else:
            _AS.update(key, v1, v2)
    except ValueError as exc:
        raise PropertyRangeError(f"CoolProp failed at {name1}={v1}, {name2}={v2}: {exc}") from exc
    phase = _phase_name(_AS.phase())
    if phase == "twophase":
        # transport properties undefined for a two-phase mixture -> flag loudly
        raise PropertyRangeError(f"two-phase state at {name1}={v1}, {name2}={v2}")
    return State(P=_AS.p(), T=_AS.T(), rho=_AS.rhomass(), h=_AS.hmass(), s=_AS.smass(),
                 mu=_AS.viscosity(), cp=_AS.cpmass(), phase=phase)


def state_PT(P, T) -> State:
    _guard_PT(P, T)
    return _state("P", P, "T", T)


def state_Ph(P, h) -> State:
    if not (0 < P <= P_MAX):
        raise PropertyRangeError(f"P={P:.3e} Pa outside range")
    return _state("P", P, "H", h)


def h_Ps(P, s) -> float:
    return CP.PropsSI("H", "P", P, "S", s, FLUID)


def T_Ps(P, s) -> float:
    return CP.PropsSI("T", "P", P, "S", s, FLUID)


def s_Ph(P, h) -> float:
    return CP.PropsSI("S", "P", P, "H", h, FLUID)


def T_sat(P) -> float:
    """Saturation temperature (only defined below the critical pressure)."""
    if P >= P_CRIT:
        raise PropertyRangeError("no saturation temperature above the critical pressure")
    return CP.PropsSI("T", "P", P, "Q", 0, FLUID)


def P_sat(T) -> float:
    if T >= T_CRIT:
        raise PropertyRangeError("no saturation pressure above the critical temperature "
                                 f"({T_CRIT - 273.15:.2f} C): CO2 cannot condense")
    return CP.PropsSI("P", "T", T, "Q", 0, FLUID)


def ideal_gas_density(P, T) -> float:
    """Ideal-gas density, used as a limiting-case check at low pressure."""
    return P * M_MOLAR / (8.314462618 * T)


def compare_property_grid(sim_fn, prop: str, P_values, T_values, reference_offset=None):
    """Compare a simulator property function ``sim_fn(P, T) -> value`` with CoolProp.

    ``prop`` is one of rho, h, s, mu, cp. Returns a list of dict rows with the relative error;
    near-critical points are flagged. Note: enthalpy/entropy reference states differ between
    libraries; for those, pass a ``sim_fn`` that returns h(P,T) - h(P0,T0) and compare it with
    the same difference from CoolProp (``reference_offset`` does the subtraction for you).
    """
    offset = 0.0
    if reference_offset is not None:
        P0, T0 = reference_offset
        offset = getattr(state_PT(P0, T0), prop)
    rows = []
    for P in P_values:
        for T in T_values:
            try:
                ref = getattr(state_PT(P, T), prop) - offset
            except (PropertyRangeError, ValueError) as exc:
                rows.append({"P": P, "T": T, "ref": None, "sim": None, "rel_err": None,
                             "note": f"reference undefined: {exc}"})
                continue
            sim = sim_fn(P, T)
            rel = abs(sim - ref) / abs(ref) if ref else abs(sim - ref)
            rows.append({"P": P, "T": T, "ref": ref, "sim": sim, "rel_err": rel,
                         "near_critical": is_near_critical(P, T)})
    return rows
