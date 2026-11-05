# Validation methods: finding gaps before reading every line

The idea is the same one accountants use: you don't read every transaction to know the books
are wrong. You check that the balance sheet balances, the trial balance ties out, and the
sub-ledgers roll forward. If they don't, you know there is an error and roughly where it is.
Then you dig.

For a CO2-EGS simulator and TEA, the equivalents are conservation laws, accounting identities,
definitional identities and invariances. None of them needs a "right answer" to compare against.

## The workflow

```
DETECT     cheap whole-model checks (balances, tie-outs, invariances)  -> scorecard
  |
LOCALIZE   re-run the failing check per component / per year / per calc-sheet step
  |        -> the FIRST place it breaks
DIAGNOSE   hand-check and code-read only that piece
  |
CONFIRM    fix it in a scratch copy, re-run: the check must now pass and nothing else break
  |
GUARD      keep the check as a regression test
```

A FAIL is a **lead**, not a finding. It becomes a finding once it's localized and explained.

## A. Balances and closures (conservation laws)

| Check | Identity | Toolkit |
|---|---|---|
| Energy balance | heat in + work in = work out + heat rejected + losses (every time step) | `checks.energy_balance` |
| Mass balance | injected = produced + lost + change in inventory | `checks.mass_balance` |
| Pressure loop | signed pressure changes around the circulation loop sum to zero | `checks.pressure_loop` |
| Entropy | entropy generated in each adiabatic component is at least zero | `checks.entropy_generation` |
| Carbon ledger | CO2 purchased = stored + vented + change in inventory; credited is at most stored | `checks.carbon_ledger` |
| Sources = uses | debt + equity + grants = capex + interest during construction + fees | `checks.sources_uses` |
| Balance sheet | assets = liabilities + equity, every year | `checks.balance_sheet` |

What a failure usually means: a term is missing (fan power, wellbore heat loss, lost-CO2
enthalpy), a flow is applied to the wrong stream (injected vs produced mass flow), or there's a
sign error. A negative entropy generation almost always means an efficiency was applied in the
wrong direction.

## B. Tie-outs and reconciliations (accounting)

| Method | What it catches | Toolkit |
|---|---|---|
| **Tie-out**: every reported number traces to a model output | stale pasted numbers, hidden overrides, numbers with no source | `checks.tie_out` |
| **Footing**: parts sum to the total | missing or double-counted cost lines | `checks.footing` |
| **Cross-footing**: rows and columns both sum to the same grand total | spreadsheet range errors | `checks.cross_footing` |
| **Roll-forward**: opening + additions − deductions = closing, and closing = next opening | CO2 inventory, debt and depreciation schedule errors | `checks.roll_forward` |
| **Two-path reconciliation**: one quantity computed two independent ways | formula errors on either path | `checks.two_path` |
| **LCOE definitional test**: NPV = 0 at price = LCOE, and IRR = discount rate | any LCOE formula error | `checks.npv_at_lcoe`, `finance.irr` |
| **Signature checks**: does the reported LCOE equal a known-wrong formula? | undiscounted energy, real rate on nominal flows, no discounting | `adapter.lcoe_checks` |
| **Variance bridge**: break a case-to-case change into per-input contributions | hidden coupling between inputs; inconsistent input plumbing | `metamorphic.variance_bridge` |

Two-path pairs worth building:
- LCOE from discounted cash flows vs the CRF shortcut. They must agree when output and costs
  are constant and there are no taxes.
- Net power per component vs gross power minus total parasitics.
- Accumulated depreciation vs the depreciable basis.
- Capex in the cash-flow table vs the capex total, in real and nominal dollars.

## C. Invariance and scaling (metamorphic testing)

| Transform | Required result |
|---|---|
| All $ inputs × k (costs *and* credits) | LCOE × k exactly |
| All extensive inputs × k (doublets, flow, wells, equipment) | power × k, LCOE unchanged (if nothing is meant to scale non-linearly) |
| Inflation changed, no taxes, real inputs | real LCOE unchanged |
| Discount rate = 0, no taxes | LCOE = Σ cost / Σ MWh |
| Units changed (SI ↔ field, MW ↔ kW) | identical outputs |
| Finer grid / time step | output converges; observed order of accuracy is reasonable |

Toolkit: `metamorphic.scaling`, `invariance`, `convergence`.

## D. Limiting cases and bounds

- Zero flow → zero power. Zero temperature difference → zero net power. Zero friction → a purely hydrostatic column.
- Low-pressure CO2 → ideal-gas density.
- Water as the working fluid → published brine-EGS behaviour.
- Net power ≤ the exergy flow of the produced fluid. Cycle efficiency < Carnot efficiency.
- All densities, pressures, absolute temperatures and costs positive and finite.

Toolkit: `checks.carnot_bound`, `exergy_bound`, `positivity`, `finite`.

## E. Sweeps: direction and smoothness

- **Direction of change**: LCOE rises with drilling cost and discount rate; power rises with
  reservoir temperature; deeper wells mean hotter rock *and* more friction, so check both signs.
- **Kinks and jumps**: sweep each input and look for discontinuities. Common causes are
  phase-boundary branches, solvers that stop before converging, coarse property tables, and
  `if/else` thresholds.
- **Elasticity**: d ln LCOE / d ln(capex item) should equal that item's share of LCOE.

Toolkit: `metamorphic.monotonic`, `kinks`, `elasticity`.

## F. Independent recomputation (hand-checks)

- **Calc sheets** (`calcsheet.CalcSheet`) follow the chain input → properties → wells →
  reservoir → plant → energy → costs → LCOE, one step at a time, each with its equation, source,
  inputs, result, simulator value and tolerance. The first step that diverges is where the bug is.
- **Back-of-envelope estimates** (tolerance class `estimate`) catch order-of-magnitude errors,
  for example a column head of about ρ̄gH, LCOE ≈ CRF·capex/MWh + O&M, and W_net ≪ Carnot·Q.
- **Second implementation**: the toolkit's wellbore, turbine and finance modules are
  independent reimplementations to run side by side with the simulator.

## G. Code-level bug finding

| Method | What it gives you |
|---|---|
| Property-based testing (e.g. Hypothesis) | thousands of random valid inputs, each checked against A–E |
| Boundary and fuzz inputs | near-critical states, property-table edges, zeros and extremes; catches NaN/inf and silent extrapolation |
| Runtime invariant assertions | a broken balance stops the run instead of producing a plausible-looking wrong number |
| **Mutation testing** | plant bugs deliberately (flip a sign, change an efficiency) and see whether the tests catch them; this measures how much the tests can be trusted (see `tests/test_checks.py`) |
| Static analysis | type checks, linters, dimensional analysis of each equation |
| Differential and regression testing | compare outputs across versions; `git bisect` the commit that moved a headline number |
| Traceability matrix | every documented equation ↔ a line of code, and vice versa |

## H. Input provenance

Every input has a source and a cost-year. Inputs without a source go in the assumptions
register, ranked by how sensitive the results are to them.

## Tolerance classes

Tolerances are set by the kind of calculation, never loosened until a check passes.

| Class | Relative tolerance | Use for |
|---|---|---|
| `exact` | 1e-6 | arithmetic: finance, footing, tie-outs |
| `property` | 1e-3 | equation-of-state lookups |
| `balance` | 5e-3 | whole-system closure in a numerical simulator |
| `discretized` | 1e-2 | integrated wellbore or reservoir quantities |
| `estimate` | 0.25 | back-of-envelope sanity checks |
