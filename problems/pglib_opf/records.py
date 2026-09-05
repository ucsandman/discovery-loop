"""PGLib-OPF published baseline (PowerModels.jl + IPOPT, from BASELINE.md in the pglib-opf repo) and case download.

The table lists the AC-OPF objective ($/h) to five significant figures per case, so a "better" result must clear
it by more than that rounding (see problem.WIN_MARGIN). Cases (.m, MATPOWER format) download on first use.
"""

import os
import re
import urllib.request
from decimal import Decimal

VERSION = "v23.07"  # the tag BASELINE.md was computed against; case files are pinned to it
RAW = f"https://raw.githubusercontent.com/power-grid-lib/pglib-opf/{VERSION}/"
HERE = os.path.dirname(os.path.abspath(__file__))
INSTANCES = os.path.join(HERE, "instances")
BASELINE = os.path.join(HERE, "BASELINE.md")


def _parse(path):
    """{case: {"nodes", "edges", "dc", "ac", "qc_gap", "soc_gap"}} across all three operating conditions."""
    rec = {}
    for line in open(path, encoding="utf-8"):
        m = re.match(
            r"\|\s*(pglib_opf_\S+)\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|\s*([\d.e+-]+)\s*\|\s*([\d.e+-]+)\s*\|\s*([\d.-]+|inf\.?|--)\s*\|\s*([\d.-]+|inf\.?|--)",
            line,
        )
        if not m:
            continue
        name, nodes, edges, dc, ac, qc, soc = m.groups()
        rec[name] = {
            "nodes": int(nodes),
            "edges": int(edges),
            "dc": float(dc),
            "ac": float(ac),
            "qc_gap": float(qc) if re.match(r"[\d.-]+$", qc) else None,
            "soc_gap": float(soc) if re.match(r"[\d.-]+$", soc) else None,
        }
    return rec


def table():
    return _parse(BASELINE) if os.path.exists(BASELINE) else fetch_table()


def baseline_uncertainty(name):
    """Half one unit in the last printed AC-objective digit for ``name``."""
    for line in open(BASELINE, encoding="utf-8"):
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) >= 5 and cells[0] == name:
            value = Decimal(cells[4])
            last_place = value.adjusted() - len(value.as_tuple().digits) + 1
            return float(Decimal("0.5") * (Decimal(10) ** last_place))
    raise KeyError(f"{name} has no printed AC objective in {BASELINE}")


def fetch_table():
    urllib.request.urlretrieve(RAW + "BASELINE.md", BASELINE)
    return _parse(BASELINE)


def load():
    """{case: published AC objective} for the loop (the value to beat)."""
    return {k: v["ac"] for k, v in table().items()}


def fetch():
    return {k: v["ac"] for k, v in fetch_table().items()}


def case_path(name):
    """Local .m file for a case, downloading from the pglib-opf repo on first use (api/sad variants live in subdirs)."""
    p = os.path.join(INSTANCES, name + ".m")
    if not os.path.exists(p):
        os.makedirs(INSTANCES, exist_ok=True)
        sub = "api/" if name.endswith("__api") else "sad/" if name.endswith("__sad") else ""
        urllib.request.urlretrieve(RAW + sub + name + ".m", p)
    return p


if __name__ == "__main__":
    import sys

    t = fetch_table() if "--fetch" in sys.argv else table()
    print(f"{len(t)} cases in {os.path.basename(BASELINE)}")
    for n in sys.argv[1:]:
        if n.startswith("pglib"):
            print(n, case_path(n), t.get(n))
