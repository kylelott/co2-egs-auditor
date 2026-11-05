"""One command for everything.

    python -m egs_audit.run_all                       # toolkit self-check on the reference case
    python -m egs_audit.run_all --sim outputs.json    # + every check on a simulator export
    python -m egs_audit.run_all --sim outputs.json --out audit_output

Writes scorecards, the reference calc sheet and the reference cash-flow table to --out.
Exit code is 1 if any check FAILs (so it can gate CI).
"""

from __future__ import annotations

import argparse
import os
import sys

from . import adapter, finance, reference, scorecard


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sim", help="simulator outputs JSON (see examples/simulator_outputs.example.json)")
    ap.add_argument("--out", default="audit_output", help="output directory")
    ap.add_argument("--skip-reference", action="store_true", help="skip the reference self-check")
    a = ap.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)
    failed = False

    if not a.skip_reference:
        r = reference.run()
        res = reference.balance_checks(r)
        sheet = reference.calc_sheet(r)
        with open(os.path.join(a.out, "reference_scorecard.md"), "w") as fh:
            fh.write(scorecard.to_markdown(res, "Reference case: toolkit self-check"))
        with open(os.path.join(a.out, "reference_calc_sheet.md"), "w") as fh:
            fh.write(sheet.to_markdown())
        with open(os.path.join(a.out, "reference_cash_flows.md"), "w") as fh:
            fh.write("# Reference case cash-flow table (nominal $)\n\n")
            fh.write(finance.format_table(r["finance"].table))
        s = scorecard.summary(res)
        print(f"reference self-check: {s}")
        failed |= s["FAIL"] > 0

    if a.sim:
        sim = adapter.load(a.sim)
        res = adapter.run(sim)
        with open(os.path.join(a.out, "simulator_scorecard.md"), "w") as fh:
            fh.write(scorecard.to_markdown(res, f"Simulator checks: {a.sim}"))
        s = scorecard.summary(res)
        print(f"simulator checks: {s}")
        failed |= s["FAIL"] > 0

    print(f"reports written to {os.path.abspath(a.out)}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
