"""CVRP solver: Clarke-Wright start, pruned granular local search, string/route ruin & recreate with SA.

Phase 1: parallel Clarke-Wright savings -> feasible routes, written to disk immediately.
Phase 2: granular local search (each customer only paired with its K nearest neighbours, scanned in
         increasing distance and cut off as soon as the candidate edge is longer than the longest edge
         currently incident to the customer) with relocate / Or-opt (1-3 customers, optionally reversed),
         swap 1-1, inter-route segment swaps (2-1, 1-2, 2-2), intra-route 2-opt and inter-route 2-opt*;
         every move is capacity checked.  After a move only the endpoints of the changed edges are re-queued.
Phase 3: until the deadline, SISR-style ruin (adjacent / split strings around a random seed, occasionally a
         whole route plus strings around it so vehicles can be eliminated, occasionally random customers)
         + neighbour-adjacent cheapest insertion with blinks (full scan only when no neighbour slot fits)
         + pruned local search on the touched customers, accepted with simulated annealing (restart from the
         incumbent on stagnation); the best solution is saved atomically on every improvement.  A final
         unpruned full local search polishes the incumbent.

    python solver.py --target X-n280-k17 --time 120 --seed 1 --out sol.json
Pure python + numpy.
"""

import argparse
import json
import math
import os
import random
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # standalone use; the loop also sets PYTHONPATH
from verify import dist_matrix, load_instance  # noqa: E402

INF = float("inf")


def clarke_wright(D, demand, cap):
    """Parallel savings. Returns a list of routes (lists of customer node indices 1..n)."""
    n = len(demand) - 1
    routes = {i: [i] for i in range(1, n + 1)}
    where = {i: i for i in range(1, n + 1)}
    load = {i: float(demand[i]) for i in range(1, n + 1)}
    cust = np.arange(1, n + 1)
    i, j = np.meshgrid(cust, cust, indexing="ij")
    mask = i < j
    sav = (D[0, i] + D[0, j] - D[i, j])[mask]
    order = np.argsort(-sav, kind="stable")
    ii, jj = i[mask][order], j[mask][order]
    for a, b in zip(ii.tolist(), jj.tolist()):
        ra, rb = where[a], where[b]
        if ra == rb or load[ra] + load[rb] > cap:
            continue
        Ra, Rb = routes[ra], routes[rb]
        if a not in (Ra[0], Ra[-1]) or b not in (Rb[0], Rb[-1]):
            continue
        if Ra[-1] != a:
            Ra.reverse()
        if Rb[0] != b:
            Rb.reverse()
        merged = Ra + Rb
        for c in Rb:
            where[c] = ra
        routes[ra] = merged
        load[ra] += load[rb]
        del routes[rb]
    return list(routes.values())


class CVRP:
    def __init__(self, Dn, demand, cap, rng, K=20, Kruin=50):
        self.Dn = Dn
        self.D = Dn.tolist()
        self.n = len(demand) - 1
        self.dem = [int(x) if float(x).is_integer() else float(x) for x in demand]
        self.cap = int(cap) if float(cap).is_integer() else float(cap)
        self.rng = rng
        n = self.n
        order = np.argsort(Dn[1:, 1:], axis=1, kind="stable")
        self.nb = [None] * (n + 1)
        self.nbr = [None] * (n + 1)
        for c in range(1, n + 1):
            row = [int(x) + 1 for x in order[c - 1].tolist() if int(x) + 1 != c]
            self.nb[c] = row[:K]
            self.nbr[c] = row[:Kruin]
        self.D0 = self.D[0]
        self.aff = ()

    # ------------------------------------------------------------------ utilities
    def route_cost(self, R):
        if not R:
            return 0
        D = self.D
        s = D[0][R[0]] + D[R[-1]][0]
        for k in range(len(R) - 1):
            s += D[R[k]][R[k + 1]]
        return s

    def total_cost(self, routes):
        return sum(self.route_cost(R) for R in routes)

    def compact(self, routes):
        routes = [R[:] for R in routes if R]
        rid = [-1] * (self.n + 1)
        load = []
        dem = self.dem
        for r, R in enumerate(routes):
            for x in R:
                rid[x] = r
            load.append(sum(dem[x] for x in R))
        return routes, rid, load

    # ------------------------------------------------------------------ local search
    def _set2(self, routes, rid, load, rc, rv, A, B):
        dem = self.dem
        routes[rc] = A
        routes[rv] = B
        for x in A:
            rid[x] = rc
        for x in B:
            rid[x] = rv
        load[rc] = sum(dem[x] for x in A)
        load[rv] = sum(dem[x] for x in B)

    def _improve(self, c, v, routes, rid, load):
        D = self.D
        dem = self.dem
        cap = self.cap
        rc = rid[c]
        rv = rid[v]
        Rc = routes[rc]
        Rv = routes[rv]
        i = Rc.index(c)
        j = Rv.index(v)
        lc = len(Rc)
        lv = len(Rv)
        pc = Rc[i - 1] if i else 0
        nc = Rc[i + 1] if i + 1 < lc else 0
        pv = Rv[j - 1] if j else 0
        nv = Rv[j + 1] if j + 1 < lv else 0
        Dc = D[c]
        Dv = D[v]
        Dpc = D[pc]
        Dpv = D[pv]
        dc = dem[c]
        dv = dem[v]
        same = rc == rv
        Lc = load[rc]
        Lv = load[rv]

        # ---- swap c <-> v
        if same:
            if j == i + 1:
                delta = Dpc[v] + Dc[nv] - Dpc[c] - Dv[nv]
            elif i == j + 1:
                delta = Dpv[c] + Dv[nc] - Dpv[v] - Dc[nc]
            else:
                delta = Dpc[v] + Dv[nc] + Dpv[c] + Dc[nv] - Dpc[c] - Dc[nc] - Dpv[v] - Dv[nv]
            if delta < 0:
                Rc[i] = v
                Rc[j] = c
                self.aff = (c, v, pc, nc, pv, nv)
                return True
        else:
            if Lc - dc + dv <= cap and Lv - dv + dc <= cap:
                delta = Dpc[v] + Dv[nc] + Dpv[c] + Dc[nv] - Dpc[c] - Dc[nc] - Dpv[v] - Dv[nv]
                if delta < 0:
                    Rc[i] = v
                    Rv[j] = c
                    rid[c] = rv
                    rid[v] = rc
                    load[rc] = Lc - dc + dv
                    load[rv] = Lv - dv + dc
                    self.aff = (c, v, pc, nc, pv, nv)
                    return True
            # ---- segment swaps (2,1), (2,2), (1,2) between different routes
            if i + 1 < lc:
                c2 = Rc[i + 1]
                nc2 = Rc[i + 2] if i + 2 < lc else 0
                d2 = dem[c2]
                Dc2 = D[c2]
                if Lc - dc - d2 + dv <= cap and Lv - dv + dc + d2 <= cap:
                    delta = Dpc[v] + Dv[nc2] + Dpv[c] + Dc2[nv] - Dpc[c] - Dc2[nc2] - Dpv[v] - Dv[nv]
                    if delta < 0:
                        Rc[i : i + 2] = [v]
                        Rv[j : j + 1] = [c, c2]
                        rid[v] = rc
                        rid[c] = rv
                        rid[c2] = rv
                        load[rc] = Lc - dc - d2 + dv
                        load[rv] = Lv - dv + dc + d2
                        self.aff = (c, v, c2, pc, nc2, pv, nv)
                        return True
                if j + 1 < lv:
                    v2 = Rv[j + 1]
                    nv2 = Rv[j + 2] if j + 2 < lv else 0
                    dv2 = dem[v2]
                    if Lc - dc - d2 + dv + dv2 <= cap and Lv - dv - dv2 + dc + d2 <= cap:
                        delta = Dpc[v] + D[v2][nc2] + Dpv[c] + Dc2[nv2] - Dpc[c] - Dc2[nc2] - Dpv[v] - D[v2][nv2]
                        if delta < 0:
                            Rc[i : i + 2] = [v, v2]
                            Rv[j : j + 2] = [c, c2]
                            rid[v] = rc
                            rid[v2] = rc
                            rid[c] = rv
                            rid[c2] = rv
                            load[rc] = Lc - dc - d2 + dv + dv2
                            load[rv] = Lv - dv - dv2 + dc + d2
                            self.aff = (c, v, c2, v2, pc, nc2, pv, nv2)
                            return True
            if j + 1 < lv:
                v2 = Rv[j + 1]
                nv2 = Rv[j + 2] if j + 2 < lv else 0
                dv2 = dem[v2]
                if Lc - dc + dv + dv2 <= cap and Lv - dv - dv2 + dc <= cap:
                    delta = Dpc[v] + D[v2][nc] + Dpv[c] + Dc[nv2] - Dpc[c] - Dc[nc] - Dpv[v] - D[v2][nv2]
                    if delta < 0:
                        Rc[i : i + 1] = [v, v2]
                        Rv[j : j + 2] = [c]
                        rid[v] = rc
                        rid[v2] = rc
                        rid[c] = rv
                        load[rc] = Lc - dc + dv + dv2
                        load[rv] = Lv - dv - dv2 + dc
                        self.aff = (c, v, v2, pc, nc, pv, nv2)
                        return True

        # ---- 2-opt (same route) / 2-opt* (different routes)
        if same:
            if i < j:
                if Dc[v] + D[nc][nv] - Dc[nc] - Dv[nv] < 0:
                    Rc[i + 1 : j + 1] = Rc[i + 1 : j + 1][::-1]
                    self.aff = (c, v, pc, nc, pv, nv)
                    return True
                if Dpc[pv] + Dc[v] - Dpc[c] - Dpv[v] < 0:
                    Rc[i:j] = Rc[i:j][::-1]
                    self.aff = (c, v, pc, nc, pv, nv)
                    return True
            else:
                if Dv[c] + D[nv][nc] - Dv[nv] - Dc[nc] < 0:
                    Rc[j + 1 : i + 1] = Rc[j + 1 : i + 1][::-1]
                    self.aff = (c, v, pc, nc, pv, nv)
                    return True
                if Dpv[pc] + Dv[c] - Dpv[v] - Dpc[c] < 0:
                    Rc[j:i] = Rc[j:i][::-1]
                    self.aff = (c, v, pc, nc, pv, nv)
                    return True
        else:
            d1 = Dc[nv] + Dv[nc] - Dc[nc] - Dv[nv]
            d2 = Dpc[pv] + Dc[v] - Dpc[c] - Dpv[v]
            d3 = Dc[v] + Dpv[nc] - Dc[nc] - Dpv[v]
            d4 = Dv[c] + Dpc[nv] - Dpc[c] - Dv[nv]
            if d1 < 0 or d2 < 0 or d3 < 0 or d4 < 0:
                prec = 0
                for x in Rc[: i + 1]:
                    prec += dem[x]
                prev = 0
                for x in Rv[: j + 1]:
                    prev += dem[x]
                if d1 < 0 and prec + Lv - prev <= cap and prev + Lc - prec <= cap:
                    self._set2(routes, rid, load, rc, rv, Rc[: i + 1] + Rv[j + 1 :], Rv[: j + 1] + Rc[i + 1 :])
                    self.aff = (c, v, pc, nc, pv, nv)
                    return True
                if d2 < 0 and prec - dc + prev - dv <= cap and Lc - prec + dc + Lv - prev + dv <= cap:
                    self._set2(routes, rid, load, rc, rv, Rc[:i] + Rv[:j][::-1], Rc[i:][::-1] + Rv[j:])
                    self.aff = (c, v, pc, nc, pv, nv)
                    return True
                if d3 < 0 and prec + Lv - prev + dv <= cap and prev - dv + Lc - prec <= cap:
                    self._set2(routes, rid, load, rc, rv, Rc[: i + 1] + Rv[j:], Rv[:j] + Rc[i + 1 :])
                    self.aff = (c, v, pc, nc, pv, nv)
                    return True
                if d4 < 0 and prev + Lc - prec + dc <= cap and prec - dc + Lv - prev <= cap:
                    self._set2(routes, rid, load, rc, rv, Rv[: j + 1] + Rc[i:], Rc[:i] + Rv[j + 1 :])
                    self.aff = (c, v, pc, nc, pv, nv)
                    return True

        # ---- Or-opt / relocate: move a segment containing c next to v
        segs = [(i, i + 1)]
        if i + 2 <= lc:
            segs.append((i, i + 2))
        if i + 3 <= lc:
            segs.append((i, i + 3))
        if i >= 1:
            segs.append((i - 1, i + 1))
        if i >= 2:
            segs.append((i - 2, i + 1))
        for s, e in segs:
            L = e - s
            a = Rc[s]
            b = Rc[e - 1]
            p = Rc[s - 1] if s else 0
            q = Rc[e] if e < lc else 0
            gain = D[p][a] + D[b][q] - D[p][q]
            if gain <= 0:
                continue
            if same:
                if s <= j < e:
                    continue
                ca = j != s - 1
                cb = j != e
                sd = 0
            else:
                sd = dc if L == 1 else sum(dem[x] for x in Rc[s:e])
                if Lv + sd > cap:
                    continue
                ca = cb = True
            Da = D[a]
            Db = D[b]
            mv = None
            if ca:
                base = Dv[nv] + gain
                if Dv[a] + Db[nv] < base:
                    mv = (True, False)
                elif L > 1 and Dv[b] + Da[nv] < base:
                    mv = (True, True)
            if mv is None and cb:
                base = Dpv[v] + gain
                if Dpv[a] + Db[v] < base:
                    mv = (False, False)
                elif L > 1 and Dpv[b] + Da[v] < base:
                    mv = (False, True)
            if mv is not None:
                after, rev = mv
                seg = Rc[s:e]
                del Rc[s:e]
                piece = seg[::-1] if rev else seg
                k = Rc.index(v) if same else j
                ins = k + 1 if after else k
                Rv[ins:ins] = piece
                if not same:
                    for x in seg:
                        rid[x] = rv
                    load[rc] -= sd
                    load[rv] += sd
                self.aff = (c, v, pc, nc, pv, nv, p, q, a, b)
                return True
        return False

    def local_search(self, routes, rid, load, pending, deadline, prune=True):
        nb = self.nb
        D = self.D
        improve = self._improve
        stack = [x for x in pending if x > 0]
        self.rng.shuffle(stack)
        inq = set(stack)
        tcheck = 0
        while stack:
            tcheck += 1
            if (tcheck & 63) == 0 and time.time() > deadline:
                break
            c = stack.pop()
            inq.discard(c)
            r = rid[c]
            if r < 0:
                continue
            if prune:
                # only try neighbours whose edge is no longer than the longest edge currently at c
                R = routes[r]
                i = R.index(c)
                pc = R[i - 1] if i else 0
                nc = R[i + 1] if i + 1 < len(R) else 0
                Dc = D[c]
                thr = Dc[pc] if Dc[pc] > Dc[nc] else Dc[nc]
                for v in nb[c]:
                    if Dc[v] > thr:
                        break
                    if improve(c, v, routes, rid, load):
                        for x in self.aff:
                            if x and x not in inq:
                                inq.add(x)
                                stack.append(x)
                        break  # c is re-queued via aff and re-examined with fresh edges
            else:
                for v in nb[c]:
                    if improve(c, v, routes, rid, load):
                        for x in self.aff:
                            if x and x not in inq:
                                inq.add(x)
                                stack.append(x)

    # ------------------------------------------------------------------ ruin & recreate
    def _string_ruin(self, routes, rid, load, seed, ks, Lmax, ruined, removed, cuts):
        rng = self.rng
        dem = self.dem
        for v in [seed] + self.nbr[seed]:
            if len(ruined) >= ks:
                break
            r = rid[v]
            if r < 0 or r in ruined:
                continue
            R = routes[r]
            lr = len(R)
            if lr == 0:
                continue
            l = rng.randint(1, int(min(Lmax, lr)))
            j = R.index(v)
            if l < lr and rng.random() < 0.5:
                # split string: remove l customers around a preserved block of m customers
                m = 1
                while l + m < lr and rng.random() > 0.01:
                    m += 1
                lt = l + m
                lo = max(0, j - lt + 1)
                hi = min(j, lr - lt)
                start = rng.randint(lo, hi)
                off = rng.randint(0, l)
                sub = R[start : start + lt]
                keep = sub[off : off + m]
                seg = sub[:off] + sub[off + m :]
                R[start : start + lt] = keep
                if start > 0:
                    cuts.append(R[start - 1])
                cuts.append(keep[0])
                cuts.append(keep[-1])
                if start + m < len(R):
                    cuts.append(R[start + m])
            else:
                lo = max(0, j - l + 1)
                hi = min(j, lr - l)
                start = rng.randint(lo, hi)
                seg = R[start : start + l]
                del R[start : start + l]
                if start > 0:
                    cuts.append(R[start - 1])
                if start < len(R):
                    cuts.append(R[start])
            for x in seg:
                rid[x] = -1
                load[r] -= dem[x]
            removed.extend(seg)
            ruined.add(r)

    def ruin(self, routes, rid, load, cbar):
        rng = self.rng
        dem = self.dem
        removed = []
        cuts = []
        u = rng.random()
        if u < 0.10:
            m = max(1, min(self.n - 1, int(cbar)))
            for x in rng.sample(range(1, self.n + 1), m):
                r = rid[x]
                R = routes[r]
                k = R.index(x)
                del R[k]
                if k > 0:
                    cuts.append(R[k - 1])
                if k < len(R):
                    cuts.append(R[k])
                rid[x] = -1
                load[r] -= dem[x]
                removed.append(x)
            return removed, cuts
        nr = sum(1 for R in routes if R)
        avg = self.n / max(1, nr)
        Lmax = max(1.0, min(10.0, avg))
        kmax = max(1, int(4.0 * cbar / (1.0 + Lmax) - 1.0))
        ks = rng.randint(1, kmax)
        ruined = set()
        if u < 0.16 and nr > 1:
            # whole-route ruin: empty a lightly loaded route, then strings around it to make room
            cand = [r for r, R in enumerate(routes) if R]
            pick = rng.sample(cand, min(3, len(cand)))
            r = min(pick, key=lambda x: load[x])
            R = routes[r]
            for x in R:
                rid[x] = -1
            removed.extend(R)
            load[r] = 0
            del R[:]
            ruined.add(r)
            seed = rng.choice(removed)
            ks += 1
        else:
            seed = rng.randint(1, self.n)
        self._string_ruin(routes, rid, load, seed, ks, Lmax, ruined, removed, cuts)
        return removed, cuts

    def _best_any(self, routes, load, c, dc, blink):
        """Cheapest feasible insertion over every position of every route (fallback)."""
        D = self.D
        Dc = D[c]
        cap = self.cap
        rng = self.rng
        best = INF
        br = -1
        bk = -1
        for r, R in enumerate(routes):
            if load[r] + dc > cap:
                continue
            p = 0
            k = 0
            for q in R:
                a = Dc[p] + Dc[q] - D[p][q]
                if a < best and not (blink and rng.random() < 0.01):
                    best = a
                    br = r
                    bk = k
                p = q
                k += 1
            a = Dc[p] + Dc[0] - D[p][0]
            if a < best and not (blink and rng.random() < 0.01):
                best = a
                br = r
                bk = k
        return br, bk

    def recreate(self, routes, rid, load, removed):
        D = self.D
        dem = self.dem
        cap = self.cap
        rng = self.rng
        D0 = self.D0
        nb = self.nb
        mode = rng.random()
        if mode < 0.4:
            rng.shuffle(removed)
        elif mode < 0.7:
            removed.sort(key=lambda x: -dem[x])
        elif mode < 0.85:
            removed.sort(key=lambda x: -D0[x])
        else:
            removed.sort(key=lambda x: D0[x])
        blink = rng.random() < 0.5
        for c in removed:
            dc = dem[c]
            Dc = D[c]
            best = INF
            br = -1
            bk = -1
            for u in nb[c]:
                r = rid[u]
                if r < 0 or load[r] + dc > cap:
                    continue
                R = routes[r]
                k = R.index(u)
                p = R[k - 1] if k else 0
                q = R[k + 1] if k + 1 < len(R) else 0
                du = Dc[u]
                a = Dc[p] + du - D[p][u]
                if a < best and not (blink and rng.random() < 0.01):
                    best = a
                    br = r
                    bk = k
                a = du + Dc[q] - D[u][q]
                if a < best and not (blink and rng.random() < 0.01):
                    best = a
                    br = r
                    bk = k + 1
            if br < 0:
                br, bk = self._best_any(routes, load, c, dc, blink)
            if br < 0:
                routes.append([c])
                rid[c] = len(routes) - 1
                load.append(dc)
                continue
            routes[br].insert(bk, c)
            rid[c] = br
            load[br] += dc

    # ------------------------------------------------------------------ driver
    def solve(self, routes0, deadline, polish_deadline, save):
        rng = self.rng
        n = self.n
        routes, rid, load = self.compact(routes0)
        self.local_search(routes, rid, load, range(1, n + 1), deadline)
        routes, rid, load = self.compact(routes)
        cur_cost = self.total_cost(routes)
        best_cost = cur_cost
        best_routes = [R[:] for R in routes]
        save(best_routes, best_cost)
        cur_routes, cur_rid, cur_load = routes, rid, load

        avg_edge = cur_cost / max(1, n + len(routes))
        T0 = max(1.0, 0.3 * avg_edge)
        Tf = 1.0
        t_start = time.time()
        span = max(1e-6, deadline - t_start)
        stall = 0.12 * span
        last_best_t = t_start
        while True:
            now = time.time()
            if now >= deadline:
                break
            if now - last_best_t > stall and cur_cost > best_cost:
                cur_routes, cur_rid, cur_load = self.compact(best_routes)
                cur_cost = best_cost
                last_best_t = now
            frac = min(1.0, (now - t_start) / span)
            T = T0 * (Tf / T0) ** frac
            work = [R[:] for R in cur_routes]
            wrid = cur_rid[:]
            wload = cur_load[:]
            cbar = 8.0 + rng.random() * 10.0
            removed, cuts = self.ruin(work, wrid, wload, cbar)
            if not removed:
                continue
            self.recreate(work, wrid, wload, removed)
            pending = set(removed)
            pending.update(cuts)
            for c in removed:
                R = work[wrid[c]]
                k = R.index(c)
                if k > 0:
                    pending.add(R[k - 1])
                if k + 1 < len(R):
                    pending.add(R[k + 1])
            self.local_search(work, wrid, wload, pending, deadline)
            new_cost = self.total_cost(work)
            if new_cost <= cur_cost or rng.random() < math.exp((cur_cost - new_cost) / T):
                if any(not R for R in work):
                    work, wrid, wload = self.compact(work)
                cur_routes, cur_rid, cur_load = work, wrid, wload
                cur_cost = new_cost
                if new_cost < best_cost:
                    best_cost = new_cost
                    best_routes = [R[:] for R in work if R]
                    last_best_t = time.time()
                    save(best_routes, best_cost)
        # final polish: full unpruned local search over every customer of the incumbent
        routes, rid, load = self.compact(best_routes)
        self.local_search(routes, rid, load, range(1, n + 1), polish_deadline, prune=False)
        routes = [R for R in routes if R]
        pc = self.total_cost(routes)
        if pc < best_cost:
            best_cost = pc
            best_routes = [R[:] for R in routes]
            save(best_routes, best_cost)
        return best_routes, best_cost


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", required=True)
    ap.add_argument("--time", type=float, default=120)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    t0 = time.time()
    deadline = t0 + max(3.0, a.time - 2.5)
    polish_deadline = t0 + max(3.5, a.time - 0.8)
    rng = random.Random(a.seed)
    np.random.seed(a.seed % (2**31 - 1))

    inst = load_instance(a.target)
    Dn = np.asarray(dist_matrix(inst["coords"]))
    if Dn.dtype.kind == "f" and np.all(Dn == np.rint(Dn)):
        Dn = np.rint(Dn).astype(np.int64)
    demand, cap = inst["demand"], inst["capacity"]

    def save(routes, obj):
        d = {
            "target": a.target,
            "obj": int(round(obj)),
            "solution": {"routes": [list(map(int, r)) for r in routes if r]},
        }
        tmp = a.out + ".tmp"
        with open(tmp, "w") as f:
            json.dump(d, f)
        os.replace(tmp, a.out)

    routes = clarke_wright(Dn, demand, cap)
    D = Dn.tolist()

    def rc(R):
        path = [0, *R, 0]
        return sum(D[path[k]][path[k + 1]] for k in range(len(path) - 1))

    save(routes, sum(rc(R) for R in routes))  # feasible on disk before anything else
    try:
        solver = CVRP(Dn, demand, cap, rng)
        solver.solve(routes, deadline, polish_deadline, save)
    except Exception:
        pass  # best feasible solution is already on disk


if __name__ == "__main__":
    main()
