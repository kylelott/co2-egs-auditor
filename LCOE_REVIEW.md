# LCOE expert review module (CO2-EGS)

Use this as the TEA section of the audit. Each item says what to check, how to check it with
the toolkit, and what a failure usually means.

## 1. Definition: what "correct" means

LCOE is the **constant price** (real or nominal, stated explicitly) at which the project's
after-tax NPV is exactly zero:

    sum_t  [ p_t * E_t * (1 - tax) - costs_t + tax shields_t + credits_t ] / (1 + i)^t  =  0

Without taxes this reduces to

    LCOE = sum_t costs_t / (1+r)^t   /   sum_t E_t / (1+r)^t

The **energy is discounted too**. That isn't optional: the formula follows from setting
discounted revenue (p·E_t) equal to discounted cost.

The shortcut `LCOE = (CRF * capex + FOM) / (8760 * CF * P_net) + VOM` is exact **only** if
capex is at t=0, output and costs are constant every year, and there are no taxes or credits.
CO2-EGS breaks every one of those conditions (multi-year construction, thermal drawdown, 45Q
for only some years), so the shortcut should be used as a cross-check, never as the answer.

**Toolkit:** `finance.solve()` gives the real and nominal-levelized LCOE and the full cash-flow
table. The checks `npv_at_lcoe` and `irr(cash flows at LCOE) == nominal rate` are the
definitional tests.

## 2. Checklist: general LCOE errors

| # | Check | How | Typical effect |
|---|---|---|---|
| G1 | Energy discounted | signature check in `adapter.lcoe_checks`; recompute by hand | LCOE shown 30–60 % too low |
| G2 | Real vs nominal consistent | real rate on real flows, or nominal rate on nominal flows; Fisher relation (1+i)=(1+r)(1+π), not i ≈ r+π | 5–25 % |
| G3 | Real or nominal LCOE stated | the nominal-levelized value is higher than the real one when inflation > 0; comparisons must use the same basis | apples vs oranges |
| G4 | Cost-year consistency | every cost has a cost-year; escalated with a stated index (CEPCI, PPI, GDP deflator) | 10–40 % for old drilling curves |
| G5 | Timing | capex at t=0..Nc−1, energy from t=Nc; end- vs mid-year convention stated; construction-period interest included | 3–15 % |
| G6 | Taxes and depreciation | depreciation on nominal capex, not indexed; MACRS class justified; non-depreciable items (land, CO2 fill) excluded from the basis; are tax losses usable? | 5–20 % |
| G7 | Capacity factor | applied once, not stacked with a separate availability factor that double counts downtime | up to 10 % |
| G8 | Lifetimes | plant life, reservoir life, financing term and depreciation life consistent, with replacement wells if the reservoir life is shorter than the plant life | varies |
| G9 | End of life | decommissioning, well plugging and abandonment, and post-closure CO2 monitoring | small after discounting, but must be present |
| G10 | Sensitivity | tornado or Monte Carlo over defensible ranges; recompute the top drivers independently | n/a |

## 3. Checklist: CO2-EGS-specific (usually where the big errors are)

| # | Check | Why it matters |
|---|---|---|
| E1 | **Net, not gross, power** in the denominator | CO2 systems carry large compression, pump and cooling loads. Check `W_net = W_gross − all parasitics` (two-path). |
| E2 | **Ambient-dependent cooling** | In warm conditions the CO2 may not condense (T > 31 °C, the critical temperature), so compression work jumps. An annual-average ambient temperature hides summer derating. Ask for a monthly or hourly ambient run, or at least a hot-day case. |
| E3 | **Thermal drawdown** | Production temperature, and therefore power, falls over time. An energy series held flat at year-1 power overstates energy. Look at `annual_energy_MWh` year by year. |
| E4 | **Initial CO2 fill** | Charging the reservoir can take hundreds of thousands to millions of tonnes. It's a capital cost (not depreciable). It's often left out, or wrongly treated as revenue. |
| E5 | **Make-up CO2 vs storage credit** | Lost CO2 has to be bought (cost) *and* may earn a storage credit (45Q). The tonnages must be identical. Check the carbon ledger: credited ≤ stored = purchased − vented − change in inventory. |
| E6 | **45Q mechanics** | Limited credit period (12 years under current rules, check), value per tonne and inflation indexing (`credits_escalate`), eligibility (secure geologic storage, monitoring and verification), whether direct pay or transferability is assumed, and whether stacking with geothermal production/investment tax credits is allowed. **These rules changed in 2025. Verify current law instead of trusting the model's or your own remembered values.** |
| E7 | **Credits buried in LCOE** | Report LCOE with and without credits. A credit that drives LCOE close to zero or negative means the project is a carbon-storage business that happens to make electricity. Say so explicitly. |
| E8 | **Storage-related costs** | Class VI permitting, monitoring wells, MRV, insurance and post-injection site care. They're usually missing when 45Q is claimed. |
| E9 | **Well costs** | Depth units (ft vs m) in the cost correlation, its cost-year, number of wells per doublet, stimulation, redrilling and make-up wells over the life. |
| E10 | **CO2 price and source** | A purchase price ($/t delivered) vs a negative price (paid to take CO2). Transport cost. Purity (impurities change the properties, see the physics checklist). |
| E11 | **Brine production period** | Early years may produce brine before a CO2 plume forms. Is reduced or zero power in those years modeled? |
| E12 | **Consistency with physics** | The flow rate in the TEA = the simulator's flow rate. The number of doublets matches the plant size. The CO2 loss rate matches the reservoir model. |

## 4. Procedure

1. **Export** the TEA's year-by-year table into the adapter JSON (`cash_flow_table`, `finance`,
   `costs`, `carbon`, `reported`, `model_outputs`). If the TEA is a spreadsheet, export the
   sheet's own rows. Don't rebuild them.
2. **Run** `python -m egs_audit.run_all --sim export.json`. Every FAIL is a lead.
3. **Rebuild independently** with `finance.FinanceInputs` from the TEA's *inputs* (not its
   outputs) and compare the LCOE. Compare line by line (`finance.format_table`) to find the first
   year and line item that differ.
4. **Bridge the gap**: if the LCOE values differ, change your inputs one at a time toward the
   TEA's assumptions and record how much each change moves LCOE (`metamorphic.variance_bridge`).
   The bridge must account for 100 % of the difference. Any residual is unexplained and gets
   investigated.
5. **Run the CO2-EGS checklist** (section 3) item by item, with evidence.
6. **Report** LCOE as: as-reported → corrected (with the bridge) → with and without credits →
   sensitivity range.

## 5. Back-of-envelope LCOE (do this first; takes 2 minutes)

    LCOE ≈ [CRF(r, n) × total capex + annual O&M + annual CO2 cost − annual credits] / annual net MWh

With r = 7 % and n = 30, CRF ≈ 0.081. If the model's LCOE is more than about 25 % away from
this (after allowing for taxes and drawdown), find out why before doing anything else.
