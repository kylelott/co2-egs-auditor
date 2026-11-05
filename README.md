# co2-egs-auditor

An audit prompt plus a tested Python toolkit for independently checking a CO2-EGS / CO2 Plume
Geothermal simulator and its techno-economic analysis (TEA), including its LCOE.

The approach:
1. **Detect** with checks that must hold if the model is right: energy and mass balances, a
   pressure loop that closes, accounting tie-outs, NPV = 0 at price = LCOE, scaling invariances.
2. **Hand-check** the calculation chain step by step, independently, to find the first step
   that diverges.
3. **Dig in** only where something breaks: localize → diagnose → confirm → guard.

## What's here

| File | Purpose |
|---|---|
| `AUDIT_PROMPT.md` | the prompt to paste into Claude Code at the simulator repository |
| `VALIDATION_METHODS.md` | catalogue of error-finding methods (balances, tie-outs, roll-forwards, metamorphic tests, mutation testing...) |
| `LCOE_REVIEW.md` | LCOE expert review module: definition, general and CO2-EGS-specific checklists, procedure |
| `egs_audit/` | the toolkit (see below) |
| `examples/simulator_outputs.example.json` | the export schema the adapter reads (generated from the reference case) |
| `tests/` | 67 tests, including mutation tests proving each check catches a planted bug |

## Install and run

```bash
pip install -e ".[test]"
```

```bash
pytest
```

Toolkit self-check on the built-in reference case (writes a scorecard, a calc sheet and a cash-flow table):

```bash
python -m egs_audit.run_all --out audit_output
```

Every check, run on a simulator's export:

```bash
python -m egs_audit.run_all --sim path/to/export.json --out audit_output
```

The exit code is 1 if any check fails, so it can gate CI.

## Toolkit modules

| Module | What it does |
|---|---|
| `properties` | CO2 Span–Wagner reference (CoolProp), range guards, near-critical flag, grid comparison |
| `wellbore` | steady vertical column: gravity, Colebrook friction, adiabatic energy (Δh = ±gH) |
| `turbo` | turbine / compressor / pump with isentropic efficiency in the correct direction, entropy generation |
| `finance` | year-by-year cash flows; real and nominal-levelized LCOE solved exactly; NPV, IRR, CRF, MACRS, taxes, ITC, time-limited and non-indexed credits, mid-year convention |
| `checks` | energy/mass/pressure-loop/entropy/carbon balances, sources = uses, balance sheet, footing, cross-footing, roll-forward, tie-out, two-path, NPV-at-LCOE, Carnot/exergy bounds |
| `metamorphic` | scaling, invariance, monotonicity, kink detection, grid convergence, elasticity, variance bridge |
| `calcsheet` | step-by-step hand-check sheets with the first-divergence locator, rendered to Markdown |
| `adapter` | runs every applicable check on a simulator JSON export, including LCOE *signature checks* that recognize common wrong formulas (undiscounted energy, real rate on nominal flows, no discounting) |
| `reference` | a transparent reference CO2 thermosiphon doublet with costs: a worked example and known-good model |

## Exporting from your simulator

Write a thin wrapper that runs your case and writes JSON in the shape of
`examples/simulator_outputs.example.json`. Every section is optional: missing data shows up as
SKIP. Export what the simulator **actually computed**. Never fill a field by recomputing it in
the wrapper, or the checks become circular.

## Reference case caveat

`egs_audit.reference` is a deliberately simple model (adiabatic wells, lumped reservoir
impedance, prescribed linear drawdown, single-phase CO2, illustrative costs). Its job is to
exercise and test the checks. It isn't a source of design numbers. Its default inputs
(one 100 kg/s doublet, a $20M CO2 fill) give an LCOE of about $330/MWh real. That shows
how heavily fill cost and scale weigh on a single small doublet, not what CO2-EGS costs.

## Tips

- For a large codebase, split the audit across sessions: Phases 0–2 in one, then 3–6, handing
  over the architecture map and scorecard.
- Re-run after fixes. The `audit/` checks become a regression suite.
