"""Independent steady-state vertical wellbore model for single-phase (supercritical) CO2.

Governing equations (depth z positive downward, steady flow, one dimension):

    Momentum:  dP/dz = rho*g  -  sign * f * rho * v|v| / (2 D)        (sign = +1 flowing down)
    Energy:    dh/dz = g                                         (adiabatic, no shaft work,
                                                                  kinetic energy neglected)

Friction always opposes the flow: for a downward (injection) flow it *reduces* the pressure
gain with depth, and for an upward (production) flow it *adds* to the pressure loss going up.
The energy equation follows from h + g*z_elevation = const along an adiabatic pipe, so
enthalpy rises by g per metre going down and falls by g per metre going up, regardless of
friction (friction converts pressure work into internal energy but leaves h + g*z unchanged).

Assumptions to flag when comparing with a simulator: adiabatic wall (no heat exchange with the
formation), kinetic-energy change neglected, constant diameter, fully developed turbulent flow.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from . import properties as props
from .units import G


def friction_factor_haaland(Re, rel_roughness):
    """Darcy friction factor, Haaland (1983) explicit approximation to Colebrook."""
    if Re < 2300:
        return 64.0 / max(Re, 1e-12)
    return (-1.8 * math.log10((rel_roughness / 3.7) ** 1.11 + 6.9 / Re)) ** -2


def friction_factor_colebrook(Re, rel_roughness, tol=1e-12, max_iter=100):
    """Darcy friction factor, Colebrook-White solved iteratively (raises if not converged)."""
    if Re < 2300:
        return 64.0 / max(Re, 1e-12)
    f = friction_factor_haaland(Re, rel_roughness)
    for _ in range(max_iter):
        rhs = -2.0 * math.log10(rel_roughness / 3.7 + 2.51 / (Re * math.sqrt(f)))
        f_new = rhs ** -2
        if abs(f_new - f) < tol * f:
            return f_new
        f = f_new
    raise RuntimeError("Colebrook iteration did not converge")


@dataclass
class WellResult:
    depth: list = field(default_factory=list)   # m, positive down
    P: list = field(default_factory=list)       # Pa
    T: list = field(default_factory=list)       # K
    h: list = field(default_factory=list)       # J/kg
    rho: list = field(default_factory=list)     # kg/m3
    dP_gravity: float = 0.0   # Pa, integral of rho*g dz over the column (positive)
    dP_friction: float = 0.0  # Pa, integral of friction gradient (positive magnitude)

    @property
    def inlet(self):
        return {"P": self.P[0], "T": self.T[0], "h": self.h[0], "rho": self.rho[0]}

    @property
    def outlet(self):
        return {"P": self.P[-1], "T": self.T[-1], "h": self.h[-1], "rho": self.rho[-1]}


def _gradients(P, h, m_dot, D, roughness):
    st = props.state_Ph(P, h)
    area = math.pi * D ** 2 / 4
    v = m_dot / (st.rho * area)
    Re = st.rho * abs(v) * D / st.mu
    f = friction_factor_colebrook(Re, roughness / D)
    fric = f * st.rho * v * v / (2 * D)   # Pa/m, magnitude
    grav = st.rho * G                     # Pa/m
    return st, grav, fric


def integrate_column(P_in, T_in, m_dot, depth, D, roughness=4.5e-5, n_seg=200,
                     direction="down", friction=True):
    """Integrate a vertical well from its inlet.

    direction="down": inlet at the wellhead (z=0), outlet at bottomhole (z=depth). Injection.
    direction="up":   inlet at bottomhole (z=depth), outlet at the wellhead (z=0). Production.

    Uses Heun's method (RK2) on (P, h) with properties evaluated at each sub-step.
    Returns a WellResult with the profile ordered from inlet to outlet.
    """
    if direction not in ("down", "up"):
        raise ValueError("direction must be 'down' or 'up'")
    dz = depth / n_seg
    s = 1.0 if direction == "down" else -1.0   # dz_depth per unit path length
    st0 = props.state_PT(P_in, T_in)
    P, h = P_in, st0.h
    res = WellResult()
    z = 0.0 if direction == "down" else depth

    def record(P, h, z, st):
        res.depth.append(z); res.P.append(P); res.T.append(st.T)
        res.h.append(h); res.rho.append(st.rho)

    record(P, h, z, st0)
    for _ in range(n_seg):
        # path coordinate x along the flow; dP/dx = s*rho*g - fric ; dh/dx = s*g
        st1, g1, f1 = _gradients(P, h, m_dot, D, roughness)
        f1 = f1 if friction else 0.0
        dP1 = s * g1 - f1
        dh1 = s * G
        st2, g2, f2 = _gradients(P + dP1 * dz, h + dh1 * dz, m_dot, D, roughness)
        f2 = f2 if friction else 0.0
        dP2 = s * g2 - f2
        P += 0.5 * (dP1 + dP2) * dz
        h += dh1 * dz
        res.dP_gravity += 0.5 * (g1 + g2) * dz
        res.dP_friction += 0.5 * (f1 + f2) * dz
        z += s * dz
        record(P, h, z, props.state_Ph(P, h))
    return res


def hydrostatic_estimate(rho_avg, depth):
    """Back-of-envelope column pressure: rho_avg * g * H."""
    return rho_avg * G * depth
