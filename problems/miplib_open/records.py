"""MIPLIB 2017 OPEN instances: best-known objectives, sizes, provenance, and instance/solution download.

An OPEN instance has a known feasible solution but no proof of optimality, so beating its best-known
objective with a verified feasible point is a genuine, externally creditable result (ZIB lists it). The
best-known objective per open instance is the value on the newest official .solu file's ``=best=`` line
(in the instance's own objective sense). Sizes (vars/rows/nnz/tags) come from the live "open" tag page,
and per-instance provenance (best-known objective, submitter, date, and the official .sol download id)
from each instance's detail page; all of it is cached in records.json (committed, like cvrp).

Submission of an improved solution (ZIB, verified off the live home page 2026-09-04):
  "Contributions of new solutions to open instances are always welcome, and will be made available in
   periodic updates of the web page. ... Please send your submissions to miplibsolutions@zib.de"
The address is problem.EMAIL_TO; publish.py emails verified wins there after Wes approves the send (2026-09-04).

records_load()/records_fetch() return VALUE space, not objectives: the loop uses that same dict for
beats()/score()/the scoreboard, and our per-target value is already normalised against best-known, so the
record to tie is 0.0 (negative = beats best-known). Real objectives live in records.json for INFO/BASELINE.
"""

import datetime
import gzip
import importlib.util
import json
import os
import re
import shutil
import urllib.request

SITE = "https://miplib.zib.de"
HERE = os.path.dirname(os.path.abspath(__file__))
MIPLIB = os.path.join(os.path.dirname(HERE), "miplib")
RECORDS = os.path.join(HERE, "records.json")
OPEN_TAG_HTML = os.path.join(HERE, "tag_open.html")  # cached size table (gitignored)

# The ten targets, chosen by baseline.py --select on this machine (see BASELINE.md for the full 40-instance
# screen table). Cascade: candidate = open instance where plain HiGHS (default, 2 threads) reaches a feasible
# point within 120 s and no more than 50k vars/rows / 500k nonzeros; pickable = HiGHS-to-best-known gap in
# (1e-6, 0.10] (movable) preferred over (0.10, 0.30], with gap>0.30 and HiGHS-proved-optimal ties excluded;
# ranked oldest best-known first (loosest), then smallest by nonzeros. All ten landed in the top tier.
TARGETS = [
    "assign1-10-4",
    "n3707",
    "neos-1423785",
    "n3705",
    "milo-v12-6-r1-75-1",
    "n3700",
    "ger50-17-ptp-pop-3t",
    "n370b",
    "n3709",
    "r4l4-02-tree-bounds-50",
]


def _miplib(name):
    spec = importlib.util.spec_from_file_location("miplib_" + name, os.path.join(MIPLIB, name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_R = _miplib("records")
instance_path = _R.instance_path  # solvers/verifier: from records import instance_path (shared .mps cache)


def solu_best():
    """{instance: best-known objective} for every ``=best=`` line of the newest local .solu file.

    ``=best=`` is exactly the open set: a feasible objective is known, optimality is not proven. The value
    is in the instance's own objective sense (min or max); the sense itself is read from the .mps at verify
    time, never assumed here."""
    path = _R.solu_path()
    if path is None:
        path = _R.fetch() and _R.solu_path()
    out = {}
    for line in open(path):
        p = line.split()
        if len(p) >= 3 and p[0] == "=best=":
            out[p[1]] = float(p[2])
    return out


def _parse_size_table(html):
    """{instance: {vars, bin, int, cont, rows, nonz, tags}} from a MIPLIB tag page.

    Same table shape and regex as miplib_heur.records.benchmark_table, replicated here (not imported) only
    to avoid that function's side effect of overwriting miplib_heur/benchmark_table.json with open-set rows.
    This is a pure size parser, not a verifier, so the no-fork rule (which is about the verifier) is intact.
    """
    rows = {}
    for block in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S):
        cells = [re.sub(r"<[^>]+>", "", c).strip() for c in re.findall(r"<td[^>]*>(.*?)</td>", block, re.S)]
        if len(cells) < 12 or not cells[2].isdigit():
            continue
        tags = sorted(set(re.findall(r"tag_([a-z_0-9]+)\.html", block)) - {"benchmark", "easy", "hard", "open"})
        rows[cells[0]] = {
            "vars": int(cells[2]),
            "bin": int(cells[3]),
            "int": int(cells[4]),
            "cont": int(cells[5]),
            "rows": int(cells[6]),
            "nonz": int(cells[7]),
            "tags": tags,
        }
    return rows


def open_sizes(refresh=False):
    """{instance: size dict} for every open instance, from the live 'open' tag page (cached to disk)."""
    if refresh or not os.path.exists(OPEN_TAG_HTML):
        html = urllib.request.urlopen(SITE + "/tag_open.html", timeout=60).read().decode("utf-8", "replace")
        open(OPEN_TAG_HTML, "w", encoding="utf-8").write(html)
    return _parse_size_table(open(OPEN_TAG_HTML, encoding="utf-8").read())


def _instance_html(name):
    return urllib.request.urlopen(f"{SITE}/instance_details_{name}.html", timeout=60).read().decode("utf-8", "replace")


def fetch_instance_meta(name):
    """Best-known provenance for one open instance from its detail page.

    Parses the 'Best Known Solution(s)' table (columns ID, Objective, Exact, Int/Cons/Obj Viol, Submitter,
    Date, Description) and returns the row matching the .solu best-known objective: that row's ID is the
    official .sol download id, and it carries the submitter and the date the best-known was set.
    Returns {best_known, sol_id, submitter, date}."""
    best_known = solu_best().get(name)
    html = _instance_html(name)
    i = html.find("Best Known Solution")
    seg = html[i : i + 4000] if i >= 0 else html
    candidates = []
    for block in re.findall(r"<tr[^>]*>(.*?)</tr>", seg, re.S):
        cells = [
            re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", c)).strip()
            for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", block, re.S)
        ]
        cells = [c for c in cells if c]
        if len(cells) >= 8 and cells[0].isdigit():
            try:
                obj = float(cells[1])
            except ValueError:
                continue
            candidates.append({"sol_id": int(cells[0]), "obj": obj, "submitter": cells[-3], "date": cells[-2]})
    if not candidates:
        return {"best_known": best_known, "sol_id": None, "submitter": None, "date": None}
    if best_known is not None:
        row = min(candidates, key=lambda r: abs(r["obj"] - best_known))
    else:
        row = max(candidates, key=lambda r: r["sol_id"])
    return {
        "best_known": best_known if best_known is not None else row["obj"],
        "sol_id": row["sol_id"],
        "submitter": row["submitter"] if row["submitter"] not in ("-", "") else None,
        "date": row["date"],
    }


def age_years(date_str, today=None):
    """Years between an ISO date (YYYY-MM-DD) and today; None if unparseable."""
    try:
        d = datetime.date.fromisoformat(date_str)
    except (ValueError, TypeError):
        return None
    today = today or datetime.date.today()
    return round((today - d).days / 365.25, 1)


def build_table(names, refresh=False):
    """Assemble and cache {name: {best_known, sense?, sol_id, submitter, date, age_years, vars, ...}}.

    ``sense`` is only added later by baseline.py (it reads it from HiGHS); everything else comes from the
    .solu file, the open tag page, and the instance pages. Writes records.json."""
    sizes = open_sizes(refresh=refresh)
    best = solu_best()
    prev = json.load(open(RECORDS)) if os.path.exists(RECORDS) else {}
    out = {}
    for name in names:
        meta = fetch_instance_meta(name)
        row = dict(prev.get(name, {}))
        row.update(
            {
                "best_known": meta["best_known"] if meta["best_known"] is not None else best.get(name),
                "sol_id": meta["sol_id"],
                "submitter": meta["submitter"],
                "date": meta["date"],
                "age_years": age_years(meta["date"]),
            }
        )
        row.update(sizes.get(name, {}))
        out[name] = row
    if not refresh:  # keep any names already cached that we did not just rebuild
        for k, v in prev.items():
            out.setdefault(k, v)
    json.dump(out, open(RECORDS, "w"), indent=1)
    return out


def table():
    """Full metadata table: cached records.json if present, else built live for TARGETS."""
    if os.path.exists(RECORDS):
        rec = json.load(open(RECORDS))
        missing = [t for t in TARGETS if t not in rec]
        if missing:
            raise RuntimeError(
                f"records.json missing targets {missing}; rebuild with build_table(TARGETS, refresh=True)"
            )
        return rec
    return build_table(TARGETS, refresh=True)


def best_known(name):
    v = table().get(name, {}).get("best_known")
    if v is None:
        v = solu_best().get(name)
    if v is None:
        raise KeyError(f"{name} has no =best= objective in the .solu file")
    return v


# ── value space for the loop (the record to tie is 0.0; negative beats best-known) ──
def load():
    return {t: 0.0 for t in TARGETS}


def fetch():
    return {t: 0.0 for t in TARGETS}


# ── official published best-known solution (ground truth) ──
def parse_sol(text):
    """{var: value} from a MIPLIB/SCIP .sol (skip '#' comments and '=obj='/'=...' header lines)."""
    sol = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("="):
            continue
        p = line.split()
        if len(p) >= 2:
            try:
                sol[p[0]] = float(p[1])
            except ValueError:
                pass
    return sol


def official_solution_path(name):
    """Local copy of the published best-known .sol (ungzipped), downloaded on first use for the ground-truth
    check. Uses the sol_id recorded from the instance page (the row whose objective equals =best=)."""
    sol = os.path.join(_R.INSTANCES, name + ".bks.sol")
    if not os.path.exists(sol):
        sid = table().get(name, {}).get("sol_id")
        if sid is None:
            sid = fetch_instance_meta(name)["sol_id"]
        if sid is None:
            raise RuntimeError(f"no official .sol id known for {name}")
        os.makedirs(_R.INSTANCES, exist_ok=True)
        gz = sol + ".gz"
        urllib.request.urlretrieve(f"{SITE}/downloads/solutions/{name}/{sid}/{name}.sol.gz", gz)
        with gzip.open(gz, "rb") as f, open(sol, "wb") as g:
            shutil.copyfileobj(f, g)
    return sol


if __name__ == "__main__":
    import sys

    if "--build" in sys.argv:
        build_table(TARGETS, refresh=True)
    t = table()
    print(f"{len(solu_best())} open (=best=) instances; {len(TARGETS)} targets")
    for name in TARGETS:
        v = t.get(name, {})
        print(
            f"  {name:24} vars={v.get('vars', '?'):>7} rows={v.get('rows', '?'):>7} "
            f"bks={v.get('best_known')} date={v.get('date')} age={v.get('age_years')}y by {v.get('submitter')}"
        )
