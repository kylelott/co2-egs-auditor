"""Independent hand-check and validation toolkit for CO2-EGS simulators and TEA.

Modules
-------
units        unit conversions (explicit, no hidden magic)
properties   CO2 thermophysical properties (CoolProp / Span-Wagner) with range guards
wellbore     independent vertical wellbore column integration (thermosiphon)
turbo        turbine / compressor / pump with isentropic efficiency
finance      year-by-year cash-flow engine: LCOE, NPV, IRR, CRF, MACRS, real vs nominal
checks       balance / closure / tie-out checks that return CheckResult objects
metamorphic  invariance, scaling, monotonicity, kink and convergence tests
calcsheet    step-by-step hand-check sheets rendered to Markdown
scorecard    pass/fail scorecard rendering
reference    a self-contained reference CO2 thermosiphon case built from the above
adapter      runs every applicable check against a simulator's exported outputs
"""

__version__ = "0.1.0"
