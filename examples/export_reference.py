"""Regenerate examples/simulator_outputs.example.json from the reference case.

    python examples/export_reference.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from egs_audit import reference  # noqa: E402

out = os.path.join(os.path.dirname(__file__), "simulator_outputs.example.json")
with open(out, "w") as fh:
    json.dump(reference.to_export(reference.run()), fh, indent=2)
print("wrote", out)
