"""Turbomachinery with isentropic efficiency, applied in the correct direction.

Expansion (turbine):    h_out = h_in - eta * (h_in - h_out_s)      ->  W = m (h_in - h_out)
Compression (compressor / pump):  h_out = h_in + (h_out_s - h_in) / eta  ->  W = m (h_out - h_in)

A very common bug is applying ``eta`` the same way for both (multiplying compression work by
eta instead of dividing), which understates parasitic load.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import properties as props


@dataclass(frozen=True)
class MachineResult:
    h_in: float
    h_out: float
    h_out_s: float
    s_in: float
    s_out: float
    T_out: float
    work_specific: float   # J/kg, positive = produced (turbine) or consumed (compressor)
    power: float           # W, positive magnitude
    entropy_gen: float     # W/K, m*(s_out - s_in); must be >= 0 for an adiabatic machine


def turbine(P_in, T_in, P_out, eta, m_dot) -> MachineResult:
    if not 0 < eta <= 1:
        raise ValueError("isentropic efficiency must be in (0, 1]")
    if P_out >= P_in:
        raise ValueError("turbine outlet pressure must be below inlet pressure")
    st_in = props.state_PT(P_in, T_in)
    h_s = props.h_Ps(P_out, st_in.s)
    h_out = st_in.h - eta * (st_in.h - h_s)
    s_out = props.s_Ph(P_out, h_out)
    T_out = props.state_Ph(P_out, h_out).T
    w = st_in.h - h_out
    return MachineResult(st_in.h, h_out, h_s, st_in.s, s_out, T_out, w, m_dot * w,
                         m_dot * (s_out - st_in.s))


def compressor(P_in, T_in, P_out, eta, m_dot) -> MachineResult:
    """Also used for pumps (dense-phase CO2) - same thermodynamics."""
    if not 0 < eta <= 1:
        raise ValueError("isentropic efficiency must be in (0, 1]")
    if P_out <= P_in:
        raise ValueError("compressor outlet pressure must be above inlet pressure")
    st_in = props.state_PT(P_in, T_in)
    h_s = props.h_Ps(P_out, st_in.s)
    h_out = st_in.h + (h_s - st_in.h) / eta
    s_out = props.s_Ph(P_out, h_out)
    T_out = props.state_Ph(P_out, h_out).T
    w = h_out - st_in.h
    return MachineResult(st_in.h, h_out, h_s, st_in.s, s_out, T_out, w, m_dot * w,
                         m_dot * (s_out - st_in.s))
