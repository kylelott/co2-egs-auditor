# co2-egs-auditor

An audit prompt for a CO2-EGS / CO2 Plume Geothermal simulator and its techno-economic analysis.

## Usage

1. Open Claude Code at the root of the simulator repo.
2. Fill in the `<<...>>` placeholders in `AUDIT_PROMPT.md` (or leave them for the auditor to infer).
3. Paste the prompt in. The auditor writes everything to `audit/` in that repo:
   - `audit/AUDIT_REPORT.md`: findings, benchmark results, assumptions register
   - `audit/benchmarks/`: independent reference calculations
   - `audit/run_all.py` (or similar): re-runs every check

## What it covers

| Phase | Focus |
|-------|-------|
| 1 | Codebase health: tests, units, solver robustness, property-library misuse, magic numbers |
| 2 | Physics: CO2 EOS, wellbore/thermosiphon, reservoir, surface plant, 1st/2nd-law invariants |
| 3 | TEA: cost basis, real vs nominal, LCOE, 45Q/credits, CO2 accounting, sensitivity |
| 4 | Independent benchmarking: unit-level reference calcs, literature cases, cross-model checks |
| 5 | Severity-ranked report with measured effect on headline outputs |

## Tips

- For a large codebase, run Phases 1–3 and Phase 4 in separate sessions, and give the second
  session the first session's architecture map.
- Re-run after fixes. The `audit/` scripts work as a regression suite.
