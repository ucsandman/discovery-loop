"""Exact verifier for matrix-multiplication tensor decompositions.

A rank-R bilinear algorithm for n x n multiplication is a list of R triples
(U_r, V_r, W_r) of n x n integer matrices such that for all A, B:

    C[e,f] = sum_r (sum_{a,b} U_r[a,b] A[a,b]) (sum_{c,d} V_r[c,d] B[c,d]) W_r[e,f]
           = sum_b A[e,b] B[b,f]

Matching coefficients of A[a,b] B[c,d] gives the tensor identity checked here:
for every (a,b,c,d,e,f), sum_r U_r[a,b] V_r[c,d] W_r[e,f] must equal
delta_{a,e} * delta_{b,c} * delta_{d,f}. All arithmetic is exact integers, so
there are no tolerances and no false positives.
"""

from __future__ import annotations

import random


def _is_int_matrix(m, n):
    if not isinstance(m, list) or len(m) != n:
        return False
    for row in m:
        if not isinstance(row, list) or len(row) != n:
            return False
        for x in row:
            if not isinstance(x, int) or isinstance(x, bool):
                return False
    return True


def check(factors, n):
    """Independently verify a decomposition. Returns a result dict.

    result = {"feasible": bool, "rank": int, "reason": str|None}
    """
    if not isinstance(n, int) or n < 2:
        return {"feasible": False, "rank": 0, "reason": "n must be an integer >= 2"}
    if not isinstance(factors, list) or not factors:
        return {"feasible": False, "rank": 0, "reason": "factors must be a non-empty list"}
    rank = len(factors)
    parsed = []
    for i, triple in enumerate(factors):
        if not isinstance(triple, (list, tuple)) or len(triple) != 3:
            return {"feasible": False, "rank": rank, "reason": f"triple {i} is not (U, V, W)"}
        u, v, w = triple
        if not _is_int_matrix(u, n) or not _is_int_matrix(v, n) or not _is_int_matrix(w, n):
            return {
                "feasible": False,
                "rank": rank,
                "reason": f"triple {i}: entries must be {n}x{n} integer matrices",
            }
        parsed.append((u, v, w))
    # Tensor identity: sum_r U_r[a,b] V_r[c,d] W_r[e,f] == d(a,e) d(b,c) d(d,f).
    for a in range(n):
        for b in range(n):
            for c in range(n):
                for d in range(n):
                    for e in range(n):
                        # Inner loop over f; hoist the (a,b,c,d,e)-dependent part.
                        ub = [u[a][b] for (u, v, w) in parsed]
                        vd = [v[c][d] for (u, v, w) in parsed]
                        for f in range(n):
                            total = 0
                            for r in range(rank):
                                total += ub[r] * vd[r] * parsed[r][2][e][f]
                            want = 1 if (a == e and b == c and d == f) else 0
                            if total != want:
                                return {
                                    "feasible": False,
                                    "rank": rank,
                                    "reason": (
                                        f"tensor identity fails at "
                                        f"(a,b,c,d,e,f)=({a},{b},{c},{d},{e},{f}): "
                                        f"got {total}, want {want}"
                                    ),
                                }
    return {"feasible": True, "rank": rank, "reason": None}


def apply(factors, A, B):
    """Evaluate the bilinear algorithm on integer matrices A, B (independent cross-check)."""
    n = len(A)
    C = [[0] * n for _ in range(n)]
    for (u, v, w) in factors:
        alpha = sum(u[a][b] * A[a][b] for a in range(n) for b in range(n))
        beta = sum(v[c][d] * B[c][d] for c in range(n) for d in range(n))
        m = alpha * beta
        if m:
            for e in range(n):
                for f in range(n):
                    C[e][f] += m * w[e][f]
    return C


def naive_product(A, B):
    n = len(A)
    return [[sum(A[a][b] * B[b][f] for b in range(n)) for f in range(n)] for a in range(n)]


# ---------------------------------------------------------------------------
# Fast randomized modular pre-filter.
#
# ADDITIVE ONLY: everything above this line (check/apply/naive_product) is
# untouched. check() remains the sole ground truth; the filter below can only
# save time, never change a verdict (see verify_fast).
# ---------------------------------------------------------------------------

# Four verified primes just below 2**31 (deterministic Miller-Rabin, bases
# 2/7/61, exact for n < 2**32). Product = 2**124.0; min prime 2147483563.
_DEFAULT_FILTER_PRIMES = (2147483647, 2147483587, 2147483579, 2147483563)


def _rand_matrix_mod(rng, n, p):
    """Uniform random n x n matrix over F_p. Uses raw getrandbits (the
    default primes are all within 84 of 2**31, so 31-bit rejection sampling
    accepts with probability > 1 - 4e-8) -- much faster than randrange."""
    gb = rng.getrandbits
    mat = []
    for _ in range(n):
        row = []
        for _ in range(n):
            x = gb(31)
            while x >= p:
                x = gb(31)
            row.append(x)
        mat.append(row)
    return mat


def _bilinear_eval_agrees(parsed, n, p, rng):
    """One randomized check of the tensor identity modulo prime p.

    Draws uniform random A, B in F_p^{n x n} and returns True iff the
    decomposition's bilinear evaluation of (A, B) equals the naive product
    AB, all mod p. Cost is O(R*n^2 + n^3) -- no n^6 tensor scan.
    """
    R = len(parsed)
    A = _rand_matrix_mod(rng, n, p)
    B = _rand_matrix_mod(rng, n, p)

    # alpha_r = (U_r . A), beta_r = (V_r . B), Frobenius inner products mod p.
    alpha = [0] * R
    beta = [0] * R
    for r in range(R):
        u, v, w = parsed[r]
        s1 = 0
        for a in range(n):
            ua = u[a]
            Aa = A[a]
            for b in range(n):
                s1 += ua[b] * Aa[b]
        s2 = 0
        for c in range(n):
            vc = v[c]
            Bc = B[c]
            for d in range(n):
                s2 += vc[d] * Bc[d]
        alpha[r] = s1 % p
        beta[r] = s2 % p

    # m_r = alpha_r * beta_r mod p; C = sum_r m_r * W_r  vs  N = A B, mod p.
    m = [(alpha[r] * beta[r]) % p for r in range(R)]
    naive = [[sum(A[e][b] * B[b][f] for b in range(n)) % p for f in range(n)]
             for e in range(n)]
    for e in range(n):
        for f in range(n):
            total = 0
            for r in range(R):
                total += m[r] * parsed[r][2][e][f]
            if total % p != naive[e][f]:
                return False
    return True


def verify_modular(factors, n, primes=_DEFAULT_FILTER_PRIMES, seed=None):
    """Randomized modular pre-filter for a decomposition.

    For each prime p in ``primes`` (fresh random evaluation point per prime),
    checks the tensor identity's bilinear consequence modulo p (see
    _bilinear_eval_agrees) and rejects on the first disagreement.

    Returns a dict with the same shape as check():
    {"feasible": bool, "rank": int, "reason": str|None}.
    ``feasible=True`` here means "survived the filter", NOT "proven valid" --
    it must always be confirmed by check() (see verify_fast). A
    ``feasible=False`` is a PROVEN rejection (soundness lemma below).

    PROOF OF THE ERROR BOUND
    ------------------------
    For output entry (e,f) define the residual polynomial in the 2n^2
    entries of (A, B):

        D_{e,f}(A,B) = sum_r (U_r.A)(V_r.B) W_r[e,f] - (AB)[e,f].

    D_{e,f} has total degree <= 2, and its coefficient of A[a,b]*B[c,d] is
    exactly the tensor residual

        S(a,b,c,d,e,f) = sum_r U_r[a,b] V_r[c,d] W_r[e,f] - [a=e][b=c][d=f].

    The decomposition is valid over Z  <=>  every S = 0  <=>  every D_{e,f}
    is the zero polynomial.

    Lemma 1 (sound rejection -- no false rejections, ever). If every S = 0
    over Z, the bilinear identity holds formally, hence mod p for every
    prime p, hence every random evaluation agrees. So a filter rejection is
    a proof of invalidity, for ANY input.

    Lemma 2 (Schwartz-Zippel). Let the decomposition be invalid, so some
    S0 != 0, and let p be a prime with p not dividing S0. Then D_{e0,f0} is
    a NONZERO polynomial of degree <= 2 over F_p, so one uniform random
    evaluation misses it with probability <= 2/p.

    Lemma 3 (prime-divisor bound). p can divide the nonzero integer S0 only
    if p <= |S0|. With rank R and largest entry magnitude M (both read off
    the input), |S0| <= R*M^3 + 1. The default primes all exceed 2.1*10^9,
    so Lemma 3's case is IMPOSSIBLE whenever R*M^3 + 1 < 2.1*10^9 -- e.g.
    R=49, M=1 gives 50, far below. Every decomposition the search produces
    (entries in {-1,0,1} or similarly small) is in this regime.

    In that regime the per-prime evaluations are independent, so

        P(false accept) <= PROD_{p in primes} (2/p)
                        <= (2 / 2147483563)^4
                        = 7.6*10^-37 ≈ 2^-120,

    cryptographically negligible. A false accept costs only time: the
    filter never skips the exact check on accept (see verify_fast).

    Outside the R*M^3+1 < min(primes) regime, Lemma 2 still bounds the
    evaluation-miss probability prime-by-prime, but Lemma 3's case can no
    longer be ruled out; verify_fast's verdict remains exact regardless,
    because it always confirms a filter pass with check().
    """
    # --- input validation: mirrors check() exactly (kept in sync by the
    # differential test; malformed input is rejected the same way) ---
    if not isinstance(n, int) or n < 2:
        return {"feasible": False, "rank": 0, "reason": "n must be an integer >= 2"}
    if not isinstance(factors, list) or not factors:
        return {"feasible": False, "rank": 0, "reason": "factors must be a non-empty list"}
    rank = len(factors)
    parsed = []
    for i, triple in enumerate(factors):
        if not isinstance(triple, (list, tuple)) or len(triple) != 3:
            return {"feasible": False, "rank": rank, "reason": f"triple {i} is not (U, V, W)"}
        u, v, w = triple
        if not _is_int_matrix(u, n) or not _is_int_matrix(v, n) or not _is_int_matrix(w, n):
            return {
                "feasible": False,
                "rank": rank,
                "reason": f"triple {i}: entries must be {n}x{n} integer matrices",
            }
        parsed.append((u, v, w))
    rng = random.Random(seed) if seed is not None else random.Random()
    for p in primes:
        if not _bilinear_eval_agrees(parsed, n, p, rng):
            return {
                "feasible": False,
                "rank": rank,
                "reason": (
                    f"modular filter rejects: bilinear identity fails mod {p} "
                    f"(sound rejection by Lemma 1; exact check skipped)"
                ),
            }
    return {"feasible": True, "rank": rank, "reason": None}


def verify_fast(factors, n, primes=_DEFAULT_FILTER_PRIMES, seed=None):
    """Drop-in replacement for check() with an identical verdict, usually faster.

    Runs the modular filter first. A filter REJECT is a proven rejection
    (Lemma 1 in verify_modular's docstring), so the exact check is skipped.
    A filter PASS is always confirmed by the exact checker. The returned
    verdict (feasible, rank) is therefore ALWAYS the exact checker's
    verdict; the filter can only save time, never change the answer.

    Best case: invalid candidates are rejected by the O(R*n^2) filter
    without the O(R*n^6) exact scan. Worst case: valid candidates pay the
    filter cost on top of the exact scan.
    """
    filt = verify_modular(factors, n, primes=primes, seed=seed)
    if not filt["feasible"]:
        return filt  # sound short-circuit: modular reject => exact reject
    return check(factors, n)
