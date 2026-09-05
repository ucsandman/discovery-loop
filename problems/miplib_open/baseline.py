"""Pick the ten target open instances a heuristic can plausibly move, on THIS machine.

Selection procedure (run for real; the resulting table is in BASELINE.md):
  candidate  = open instance where plain HiGHS (default options, 2 threads) reaches a FEASIBLE point within
               120 s, no more than --max-vars variables (default 50000), ranked so the screen stays bounded.
  target     = among candidates that are feasible in 120 s, prefer the OLDEST best-known (looser, so more
               movable) and the smallest size; carry HiGHS-at-120s gap-to-best-known as the movability signal
               (an instance HiGHS lands 0.3% from best-known is movable; one it lands 80% away is dead on
               arrival even if it is small and old).

  python baseline.py --screen                 # size-filter open instances -> candidates.json (+ dates/sizes)
  python baseline.py --measure                # run plain HiGHS 120 s on every candidate -> measured.json
  python baseline.py --select                 # print the ranked table; suggests the 10 TARGETS

Reads the open tag page for sizes and each candidate's detail page for the best-known date (records.py).
"""

import argparse
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)
from problems.miplib_open import records, verify  # noqa: E402

CAND = os.path.join(HERE, "candidates.json")
SCREEN_META = os.path.join(HERE, "screen_meta.json")
WORK = os.path.join(os.path.dirname(os.path.dirname(HERE)), "tmp", "miplib_open_baseline")


def screen(a):
    sizes = records.open_sizes(refresh=a.refresh)
    best = records.solu_best()
    keep = {}
    for name, s in sizes.items():
        if name not in best or "no_solution" in s.get("tags", []):
            continue
        if s["vars"] > a.max_vars or s["rows"] > a.max_rows or s["nonz"] > a.max_nonz:
            continue
        keep[name] = s
    names = sorted(keep, key=lambda k: keep[k]["nonz"])[: a.limit]
    json.dump(names, open(CAND, "w"), indent=1)
    print(f"{len(keep)} open instances fit the size filter; kept the {len(names)} smallest by nonzeros -> {CAND}")
    meta = json.load(open(SCREEN_META)) if os.path.exists(SCREEN_META) else {}
    for i, name in enumerate(names):
        if name not in meta:
            try:
                m = records.fetch_instance_meta(name)
            except Exception as e:
                m = {
                    "best_known": best.get(name),
                    "sol_id": None,
                    "submitter": None,
                    "date": None,
                    "note": f"{type(e).__name__}",
                }
            meta[name] = {**m, "age_years": records.age_years(m.get("date")), **keep[name]}
            json.dump(meta, open(SCREEN_META, "w"), indent=1)
            print(
                f"  meta {i + 1}/{len(names)} {name:26} vars={keep[name]['vars']:>6} "
                f"date={meta[name].get('date')} age={meta[name].get('age_years')}y",
                flush=True,
            )


def run_one(name, secs, seed):
    out = os.path.join(WORK, f"{name}.json")
    if os.path.exists(out):
        os.remove(out)
    try:
        records.instance_path(name)  # download before the clock starts
    except Exception as e:
        return name, {"feasible": False, "value": None, "note": f"download failed: {type(e).__name__}"}
    t0 = time.time()
    try:
        subprocess.run(
            [
                sys.executable,
                os.path.join(HERE, "baseline_solver.py"),
                "--target",
                name,
                "--time",
                str(secs),
                "--seed",
                str(seed),
                "--out",
                out,
            ],
            capture_output=True,
            timeout=secs + 60,
        )
    except subprocess.TimeoutExpired:
        return name, {
            "feasible": False,
            "value": None,
            "secs": round(time.time() - t0, 1),
            "note": "baseline_solver hung past the hard kill",
        }
    if not os.path.exists(out):
        return name, {
            "feasible": False,
            "value": None,
            "secs": round(time.time() - t0, 1),
            "note": "HiGHS found no feasible point in 120 s",
        }
    d = json.load(open(out))
    r = verify.check(d["solution"], name)
    return name, {
        "feasible": bool(r["feasible"]),
        "obj": r["obj"],
        "sense": r["sense"],
        "best_known": r["best_known"],
        "value": r["value"],
        "status": d.get("status"),  # kOptimal on a gap-0 instance -> effectively closed, hard-exclude
        "secs": round(time.time() - t0, 1),
        "note": "" if r["feasible"] else "HiGHS incumbent failed the 1e-6 checker",
    }


def measure(a):
    os.makedirs(WORK, exist_ok=True)
    names = json.load(open(CAND))
    res_path = os.path.join(WORK, "measured.json")
    res = json.load(open(res_path)) if os.path.exists(res_path) else {}
    todo = [n for n in names if n not in res]
    if (
        a.todo_limit
    ):  # bounded chunk so a single foreground call finishes inside the 10-min window; incremental + resumable
        todo = todo[: a.todo_limit]
    print(
        f"measuring {len(todo)} of {len([n for n in names if n not in res])} remaining ({len(names)} total), {a.secs}s each, {a.workers} in parallel",
        flush=True,
    )
    with ThreadPoolExecutor(a.workers) as ex:
        for name, r in ex.map(lambda n: run_one(n, a.secs, a.seed), todo):
            res[name] = r
            json.dump(res, open(res_path, "w"), indent=1)  # incremental: a crash keeps what was measured
            g = "infeasible" if r["value"] is None else f"{r['value']:+.4%}"
            print(f"  {name:26} feas={str(r['feasible']):5} gap-to-bks={g:<12} {r.get('note', '')}", flush=True)
    print(f"-> {res_path}")


def _tier(n, r):
    """Movability tier for a feasible candidate. Lower is better; None = never pick.

    A gap HiGHS lands 0.3 % from best-known is movable; 80 % away is dead on arrival. And an instance HiGHS
    solves to kOptimal within the screen budget is effectively closed (only a true world-record beat scores),
    so it is a hard exclusion, not a preference. The cascade fills the ten from the best tier down."""
    if r.get("status") == "kOptimal":
        return None  # HiGHS proved optimality within the screen budget: effectively closed, hard-exclude
    g = abs(r["value"])
    if 1e-6 < g <= 0.10:
        return 1  # T1: real, small, movable gap
    if 0.10 < g <= 0.30:
        return 2  # T2: bigger gap, still conceivably movable
    if g <= 1e-6:
        return 3  # T3: HiGHS ties best-known but did not prove it; only a record beat scores here
    return None  # gap > 0.30: a permanent clipped -1.0, would drown the champion total


def select(a):
    res = json.load(open(os.path.join(WORK, "measured.json")))
    meta = json.load(open(SCREEN_META)) if os.path.exists(SCREEN_META) else {}
    feas = {n: r for n, r in res.items() if r.get("feasible")}
    tier = {n: _tier(n, r) for n, r in feas.items()}
    pick = {n: t for n, t in tier.items() if t is not None}

    # rank: best tier first, then oldest best-known (loosest), then smallest by nonzeros
    def key(n):
        age = meta.get(n, {}).get("age_years")
        nonz = meta.get(n, {}).get("nonz", 1 << 30)
        return (pick[n], -(age if age is not None else 0), nonz)

    ranked = sorted(pick, key=key)
    tiername = {1: "T1<=10%", 2: "T2<=30%", 3: "T3 ties"}
    print(
        f"{len(feas)} of {len(res)} candidates feasible in {a.secs:.0f}s; {len(pick)} pickable "
        f"(T1={sum(t == 1 for t in pick.values())} T2={sum(t == 2 for t in pick.values())} "
        f"T3={sum(t == 3 for t in pick.values())})\n"
    )
    print(
        f"{'instance':26} {'tier':>7} {'vars':>7} {'rows':>7} {'bks':>14} {'age':>5} {'HiGHS gap':>11} {'status':>10}  by/date"
    )
    for n in ranked:
        m = meta.get(n, {})
        print(
            f"{n:26} {tiername[pick[n]]:>7} {m.get('vars', '?'):>7} {m.get('rows', '?'):>7} {str(m.get('best_known')):>14} "
            f"{str(m.get('age_years')):>5} {feas[n]['value']:>+10.4%} {str(feas[n].get('status')):>10}  {m.get('submitter')} {m.get('date')}"
        )
    excluded = {n: (abs(feas[n]["value"]), feas[n].get("status")) for n in feas if tier[n] is None}
    if excluded:
        print(
            f"\nexcluded ({len(excluded)}): "
            + ", ".join(f"{n}(gap={g:+.2%},{s})" for n, (g, s) in sorted(excluded.items(), key=lambda kv: kv[1][0]))
        )
    print("\nSuggested TARGETS (cascade: T1 then T2 then T3, each by oldest bks then smallest):")
    print(json.dumps(ranked[:10], indent=1))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--screen", action="store_true")
    ap.add_argument("--measure", action="store_true")
    ap.add_argument("--select", action="store_true")
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--max-vars", type=int, default=50000)
    ap.add_argument("--max-rows", type=int, default=50000)
    ap.add_argument("--max-nonz", type=int, default=500000)
    ap.add_argument("--limit", type=int, default=40)
    ap.add_argument("--secs", type=float, default=120)
    ap.add_argument(
        "--todo-limit",
        type=int,
        default=0,
        help="process at most this many un-measured candidates, then exit (chunking)",
    )
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--seed", type=int, default=1)
    a = ap.parse_args()
    if a.screen:
        screen(a)
    if a.measure:
        measure(a)
    if a.select:
        select(a)


if __name__ == "__main__":
    main()
