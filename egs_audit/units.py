"""Explicit unit conversions.

Everything inside egs_audit is SI (Pa, K, kg, m, s, J, W) unless a name says otherwise
(e.g. ``_MW``, ``_MWh``, ``_usd``). Convert at the boundary, never in the middle of a formula.
"""

G = 9.80665  # m/s^2, standard gravity

# Pressure
def bar_to_Pa(x): return x * 1e5
def MPa_to_Pa(x): return x * 1e6
def psi_to_Pa(x): return x * 6894.757293168
def Pa_to_MPa(x): return x / 1e6

# Temperature
def C_to_K(x): return x + 273.15
def K_to_C(x): return x - 273.15
def F_to_K(x): return (x - 32.0) * 5.0 / 9.0 + 273.15

# Length
FT = 0.3048  # m
def ft_to_m(x): return x * FT
def m_to_ft(x): return x / FT
def in_to_m(x): return x * 0.0254

# Permeability
MILLIDARCY = 9.869233e-16  # m^2
def mD_to_m2(x): return x * MILLIDARCY

# Energy / power
def W_to_MW(x): return x / 1e6
def MW_to_W(x): return x * 1e6
HOURS_PER_YEAR = 8760.0

# Mass
def t_to_kg(x): return x * 1000.0
def kg_to_t(x): return x / 1000.0


def escalate(cost, from_index, to_index):
    """Escalate a cost between cost-years using a price index (e.g. CEPCI, PPI).

    ``from_index`` and ``to_index`` are the index values for the two years.
    """
    return cost * to_index / from_index
