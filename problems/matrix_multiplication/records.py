"""Best-known upper bounds on the rank of n x n matrix multiplication.

n=2: 7, Strassen (1969); proven optimal by Winograd (1971) -- calibration target.
n=3: 23, Laderman (1976); lower bound 19 -- genuine open target.
n=4: 49, Strassen recursion (7^2); no stronger general construction published.
"""

from __future__ import annotations

import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))

NOTES = {
    "2": "rank 7, Strassen 1969; optimal (Winograd 1971). Calibration: a correct search must reach 7.",
    "3": "rank 23, Laderman 1976; lower bound 19. Beating 23 is a publishable result.",
    "4": "rank 49 via Strassen recursion; beatable in principle.",
}


def fetch():
    with open(os.path.join(HERE, "records.json")) as fh:
        return {str(k): int(v) for k, v in json.load(fh).items()}


def load():
    return fetch()


def table():
    rec = fetch()
    return {t: {"n": int(t), "best_known_rank": r, "note": NOTES[t]} for t, r in rec.items()}
