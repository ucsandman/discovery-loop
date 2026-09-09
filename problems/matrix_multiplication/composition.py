"""Composition engine for matrix-multiplication discovery.

Instead of searching over individual {-1,0,1} matrix entries, search over
COMPOSITIONS of known decompositions. The nightly loop's rank-26 result was
a composition: Strassen (for the 2x2 block) plus naive terms (for the
borders). This module provides:

- A Decomposition class: a named bilinear algorithm with provenance
  (name, n, rank, citation, year) and a construction tree describing
  which operator applications built it.
- REGISTRY: named decompositions with provenance. Strassen 2x2 (1969),
  naive 2x2, naive 3x3, and Laderman's rank-23 3x3 (1976), transcribed
  from Courtois et al., arXiv:1108.2830, section 2.4, and verified at
  import time with the exact tensor-identity checker in verify.py.
- Composition operators: tensor_product, block_embed, direct_sum,
  naive_fill. Each records its construction tree so explain.py can
  describe how a decomposition was built.
- search_compositions(n, max_rank, time_budget_secs, seed): enumerates
  tensor products and block-embed compositions over the registry,
  verifies each candidate with the exact checker, and returns
  (rank, decomposition) pairs sorted by rank.
"""

from __future__ import annotations

import itertools
import random
import time

from verify import check


def _E(n, i, j, s=1):
    m = [[0] * n for _ in range(n)]
    m[i][j] = s
    return m


def _add(n, *terms):
    m = [[0] * n for _ in range(n)]
    for (i, j, s) in terms:
        m[i][j] += s
    return m


def _mat_from_entries(entries, n):
    m = [[0] * n for _ in range(n)]
    for (r, c), v in entries.items():
        m[r][c] = v
    return m


def _render_construction(construction, lines, indent):
    """Append a human-readable rendering of a construction tree to lines."""
    pad = "  " * indent
    op = construction.get("op", "opaque")
    if op == "library":
        lines.append(
            f"{pad}library: {construction['name']} — {construction['citation']} "
            f"({construction['year']}), n={construction['n']}, rank={construction['rank']}"
        )
    elif op == "tensor_product":
        lines.append(f"{pad}tensor_product (n={construction['n']}, rank={construction['rank']}):")
        lines.append(f"{pad}  left:")
        _render_construction(construction["left"], lines, indent + 2)
        lines.append(f"{pad}  right:")
        _render_construction(construction["right"], lines, indent + 2)
    elif op == "block_embed":
        lines.append(
            f"{pad}block_embed of {construction['base_name']} at rows={construction['rows']}, "
            f"cols={construction['cols']} within {construction['N']}x{construction['N']} "
            f"(rank={construction['rank']})"
        )
        _render_construction(construction["base"], lines, indent + 1)
    elif op == "direct_sum":
        parts = construction["parts"]
        lines.append(
            f"{pad}direct_sum of {len(parts)} parts (total rank={construction['rank']}, "
            f"n={construction['n']}):"
        )
        for i, part in enumerate(parts):
            lines.append(f"{pad}  part {i + 1}:")
            _render_construction(part, lines, indent + 2)
    elif op == "naive_fill":
        lines.append(
            f"{pad}naive_fill: naive triples for {construction['outputs']} uncovered "
            f"outputs (rank={construction['rank']})"
        )
    elif op == "border_terms":
        lines.append(f"{pad}border_terms: {construction['note']} (rank={construction['rank']})")
    else:
        lines.append(f"{pad}{op}: {construction.get('name', '?')}")


class Decomposition:
    """A named bilinear algorithm for n×n matrix multiplication.

    Carries provenance (citation, year) and a construction tree: a dict
    describing the operator applications that built it, e.g.
    {"op": "block_embed", "base_name": "strassen-2x2", "N": 3, ...}.
    """

    def __init__(self, name, n, rank, factors_fn, description="",
                 citation="", year=None, construction=None):
        self.name = name
        self.n = n
        self.rank = rank
        self._factors_fn = factors_fn
        self.description = description
        self.citation = citation
        self.year = year
        self.construction = construction if construction is not None else {
            "op": "opaque", "name": name,
        }

    def factors(self):
        f = self._factors_fn()
        assert len(f) == self.rank, f"{self.name}: expected {self.rank}, got {len(f)}"
        return f

    def describe_construction(self):
        """Return a multi-line human-readable description of how this was built."""
        lines = []
        _render_construction(self.construction, lines, 0)
        return "\n".join(lines)

    def __repr__(self):
        return f"Decomposition({self.name}, n={self.n}, rank={self.rank})"


def _strassen_2x2_factors():
    E = lambda *t: _add(2, *t)  # noqa: E731
    return [
        [E((0, 0, 1), (1, 1, 1)), E((0, 0, 1), (1, 1, 1)), E((0, 0, 1), (1, 1, 1))],
        [E((1, 0, 1), (1, 1, 1)), E((0, 0, 1),), E((1, 0, 1), (1, 1, -1))],
        [E((0, 0, 1),), E((0, 1, 1), (1, 1, -1)), E((0, 1, 1), (1, 1, 1))],
        [E((1, 1, 1),), E((1, 0, 1), (0, 0, -1)), E((0, 0, 1), (1, 0, 1))],
        [E((0, 0, 1), (0, 1, 1)), E((1, 1, 1),), E((0, 1, 1), (0, 0, -1))],
        [E((1, 0, 1), (0, 0, -1)), E((0, 0, 1), (0, 1, 1)), E((1, 1, 1),)],
        [E((0, 1, 1), (1, 1, -1)), E((1, 0, 1), (1, 1, 1)), E((0, 0, 1),)],
    ]


def _naive_factors(n):
    triples = []
    for p in range(n):
        for q in range(n):
            for r in range(n):
                triples.append([_E(n, p, q), _E(n, q, r), _E(n, p, r)])
    return triples


def _library_construction(name, n, rank, citation, year):
    return {"op": "library", "name": name, "n": n, "rank": rank,
            "citation": citation, "year": year}


# ---------------------------------------------------------------------------
# Library of known decompositions, with provenance
# ---------------------------------------------------------------------------

STRASSEN_2X2 = Decomposition(
    "strassen-2x2", n=2, rank=7,
    factors_fn=_strassen_2x2_factors,
    description="Strassen 1969, proven optimal by Winograd 1971",
    citation="Strassen, 'Gaussian Elimination is not Optimal', 1969",
    year=1969,
    construction=_library_construction(
        "strassen-2x2", 2, 7,
        "Strassen, 'Gaussian Elimination is not Optimal', 1969", 1969),
)

NAIVE_2X2 = Decomposition(
    "naive-2x2", n=2, rank=8,
    factors_fn=lambda: _naive_factors(2),
    description="Naive O(n^3)",
    citation="folklore",
    year=None,
    construction=_library_construction("naive-2x2", 2, 8, "folklore", None),
)

NAIVE_3X3 = Decomposition(
    "naive-3x3", n=3, rank=27,
    factors_fn=lambda: _naive_factors(3),
    description="Naive O(n^3)",
    citation="folklore",
    year=None,
    construction=_library_construction("naive-3x3", 3, 27, "folklore", None),
)


# Laderman's 1976 rank-23 3x3 decomposition, transcribed from Courtois et al.,
# "A New General-Purpose Method to Multiply 3x3 Matrices Using Only 23
# Multiplications" (arXiv:1108.2830), section 2.4. Each entry is
# (U_entries, V_entries, W_entries) as {(row, col): value} dicts, 0-based.
_LADERMAN_RAW = [
    ({(0, 0): 1, (0, 1): -1, (0, 2): -1, (1, 0): 1, (1, 1): -1, (2, 1): -1, (2, 2): -1},
     {(1, 1): -1},
     {(0, 1): 1}),
    ({(0, 0): 1, (1, 0): 1},
     {(0, 1): 1, (1, 1): 1},
     {(1, 0): 1, (1, 1): 1}),
    ({(1, 1): 1},
     {(0, 0): 1, (0, 1): -1, (1, 0): 1, (1, 1): -1, (1, 2): -1, (2, 0): 1, (2, 2): -1},
     {(1, 0): 1}),
    ({(0, 0): -1, (1, 0): -1, (1, 1): 1},
     {(0, 0): -1, (0, 1): 1, (1, 1): 1},
     {(0, 1): -1, (1, 0): 1, (1, 1): 1}),
    ({(1, 0): -1, (1, 1): 1},
     {(0, 0): -1, (0, 1): 1},
     {(0, 1): 1, (1, 1): -1}),
    ({(0, 0): 1},
     {(0, 0): -1},
     {(0, 0): -1, (0, 1): -1, (0, 2): -1, (1, 0): 1, (1, 1): 1, (2, 0): 1, (2, 2): 1}),
    ({(0, 0): 1, (2, 0): 1, (2, 1): 1},
     {(0, 0): 1, (0, 2): -1, (1, 2): 1},
     {(0, 2): -1, (2, 0): 1, (2, 2): 1}),
    ({(0, 0): 1, (2, 0): 1},
     {(0, 2): -1, (1, 2): 1},
     {(2, 0): -1, (2, 2): -1}),
    ({(2, 0): 1, (2, 1): 1},
     {(0, 0): 1, (0, 2): -1},
     {(0, 2): 1, (2, 2): -1}),
    ({(0, 0): 1, (0, 1): 1, (0, 2): -1, (1, 1): -1, (1, 2): 1, (2, 0): 1, (2, 1): 1},
     {(1, 2): 1},
     {(0, 2): 1}),
    ({(2, 1): 1},
     {(0, 0): -1, (0, 2): 1, (1, 0): 1, (1, 1): -1, (1, 2): -1, (2, 0): -1, (2, 1): 1},
     {(2, 0): 1}),
    ({(0, 2): 1, (2, 1): 1, (2, 2): 1},
     {(1, 1): 1, (2, 0): 1, (2, 1): -1},
     {(0, 1): -1, (2, 0): 1, (2, 1): 1}),
    ({(0, 2): 1, (2, 2): 1},
     {(1, 1): -1, (2, 1): 1},
     {(2, 0): 1, (2, 1): 1}),
    ({(0, 2): 1},
     {(2, 0): 1},
     {(0, 0): 1, (0, 1): 1, (0, 2): 1, (1, 0): 1, (1, 2): 1, (2, 0): -1, (2, 1): -1}),
    ({(2, 1): -1, (2, 2): -1},
     {(2, 0): -1, (2, 1): 1},
     {(0, 1): 1, (2, 1): -1}),
    ({(0, 2): 1, (1, 1): 1, (1, 2): -1},
     {(1, 2): 1, (2, 0): -1, (2, 2): 1},
     {(0, 2): 1, (1, 0): 1, (1, 2): 1}),
    ({(0, 2): -1, (1, 2): 1},
     {(1, 2): 1, (2, 2): 1},
     {(1, 0): 1, (1, 2): 1}),
    ({(1, 1): 1, (1, 2): -1},
     {(2, 0): 1, (2, 2): -1},
     {(0, 2): 1, (1, 2): 1}),
    ({(0, 1): 1},
     {(1, 0): 1},
     {(0, 0): 1}),
    ({(1, 2): 1},
     {(2, 1): 1},
     {(1, 1): 1}),
    ({(1, 0): 1},
     {(0, 2): 1},
     {(1, 2): 1}),
    ({(2, 0): 1},
     {(0, 1): 1},
     {(2, 1): 1}),
    ({(2, 2): 1},
     {(2, 2): 1},
     {(2, 2): 1}),
]


def _laderman_23_factors():
    return [[_mat_from_entries(u, 3), _mat_from_entries(v, 3), _mat_from_entries(w, 3)]
            for (u, v, w) in _LADERMAN_RAW]


LADERMAN_23 = Decomposition(
    "laderman-23", n=3, rank=23,
    factors_fn=_laderman_23_factors,
    description="Laderman 1976, transcribed from Courtois et al. arXiv:1108.2830 §2.4",
    citation="Laderman, 'Noncommutative Determinants and the Rank of the 3x3 "
             "Matrix Multiplication', 1976; via Courtois et al., arXiv:1108.2830",
    year=1976,
    construction=_library_construction(
        "laderman-23", 3, 23,
        "Laderman 1976; via Courtois et al., arXiv:1108.2830", 1976),
)

# Verify the transcription with the exact tensor-identity checker before
# registering. An infeasible transcription must fail loudly here, not
# silently enter the registry.
_laderman_check = check(_laderman_23_factors(), 3)
assert _laderman_check["feasible"], (
    f"Laderman transcription failed exact verification: {_laderman_check['reason']}"
)

REGISTRY = {
    "strassen-2x2": STRASSEN_2X2,
    "naive-2x2": NAIVE_2X2,
    "naive-3x3": NAIVE_3X3,
    "laderman-23": LADERMAN_23,
}

# Backward-compatible alias for the pre-registry library dict.
LIBRARY = REGISTRY


# ---------------------------------------------------------------------------
# Composition operators
# ---------------------------------------------------------------------------

def tensor_product(A: Decomposition, B: Decomposition) -> Decomposition:
    """Bilinear algorithm for 2n×2n from two n×n algorithms. Rank multiplies."""
    assert A.n == B.n, "tensor_product requires equal dimensions"
    n = A.n

    def factors_fn():
        FA, FB = A.factors(), B.factors()
        out = []
        for (U1, V1, W1) in FA:
            for (U2, V2, W2) in FB:
                U = [[0] * (2 * n) for _ in range(2 * n)]
                V = [[0] * (2 * n) for _ in range(2 * n)]
                W = [[0] * (2 * n) for _ in range(2 * n)]
                for a in range(n):
                    for b in range(n):
                        for i in range(n):
                            for j in range(n):
                                U[2 * a + i][2 * b + j] = U1[a][b] * U2[i][j]
                                V[2 * a + i][2 * b + j] = V1[a][b] * V2[i][j]
                                W[2 * a + i][2 * b + j] = W1[a][b] * W2[i][j]
                out.append([U, V, W])
        return out

    return Decomposition(
        f"tensor({A.name},{B.name})", n=2 * n, rank=A.rank * B.rank,
        factors_fn=factors_fn,
        description=f"Tensor product: {A.description} × {B.description}",
        citation="",
        year=None,
        construction={
            "op": "tensor_product", "n": 2 * n, "rank": A.rank * B.rank,
            "left": A.construction, "right": B.construction,
        },
    )


def block_embed(decomp: Decomposition, N: int, rows: list[int], cols: list[int]) -> Decomposition:
    """Embed an n×n decomposition into specific row/col indices of an N×N problem.

    The embedded triples only touch outputs C[i][j] for i in rows, j in cols.
    Use with direct_sum to cover disjoint output blocks.
    """
    n = decomp.n
    assert len(rows) == n and len(cols) == n
    assert max(rows) < N and max(cols) < N

    def factors_fn():
        out = []
        for (U, V, W) in decomp.factors():
            Ue = [[0] * N for _ in range(N)]
            Ve = [[0] * N for _ in range(N)]
            We = [[0] * N for _ in range(N)]
            for a in range(n):
                for b in range(n):
                    # U indexes A[rows[a]][rows[b]] — input block rows×rows
                    # V indexes B[cols[a]][cols[b]] — input block cols×cols
                    # W writes C[rows[a]][cols[b]] — output block rows×cols
                    Ue[rows[a]][rows[b]] = U[a][b]
                    Ve[cols[a]][cols[b]] = V[a][b]
                    We[rows[a]][cols[b]] = W[a][b]
            out.append([Ue, Ve, We])
        return out

    return Decomposition(
        f"embed({decomp.name}@{rows}x{cols} in {N}x{N})", n=N, rank=decomp.rank,
        factors_fn=factors_fn,
        description=f"{decomp.name} embedded at rows={rows}, cols={cols}",
        construction={
            "op": "block_embed", "n": N, "rank": decomp.rank,
            "base_name": decomp.name, "base": decomp.construction,
            "N": N, "rows": list(rows), "cols": list(cols),
        },
    )


def direct_sum(*parts: Decomposition) -> Decomposition:
    """Concatenate decompositions covering disjoint outputs.

    Each part must have the same N. The union must cover all N² outputs
    exactly once (checked at factors() time via the verifier, not here).
    """
    assert len(parts) > 0
    N = parts[0].n
    assert all(p.n == N for p in parts)

    def factors_fn():
        out = []
        for p in parts:
            out.extend(p.factors())
        return out

    names = "+".join(p.name for p in parts)
    return Decomposition(
        f"direct_sum({names})", n=N, rank=sum(p.rank for p in parts),
        factors_fn=factors_fn,
        description=" + ".join(p.description for p in parts),
        construction={
            "op": "direct_sum", "n": N, "rank": sum(p.rank for p in parts),
            "parts": [p.construction for p in parts],
        },
    )


def naive_fill(N: int, covered: set[tuple[int, int]]) -> Decomposition:
    """Naive triples for outputs not covered by other parts.

    covered: set of (e, f) output indices already handled.
    Produces one triple per uncovered output: U=E(p,q), V=E(q,r), W=E(p,r).
    """
    # For output C[e][f], naive needs triples (E(e,q), E(q,f), E(e,f)) for all q
    uncovered = [(e, f) for e in range(N) for f in range(N) if (e, f) not in covered]
    rank = len(uncovered) * N

    def factors_fn():
        out = []
        for (e, f) in uncovered:
            for q in range(N):
                out.append([_E(N, e, q), _E(N, q, f), _E(N, e, f)])
        return out

    return Decomposition(
        f"naive_fill({N}x{N}, {len(uncovered)} outputs)", n=N, rank=rank,
        factors_fn=factors_fn,
        description=f"Naive fill for {len(uncovered)} uncovered outputs",
        construction={
            "op": "naive_fill", "n": N, "rank": rank,
            "N": N, "outputs": len(uncovered),
        },
    )


def _cross_terms(N: int, block: list[int]) -> Decomposition:
    """Rank-1 terms for the cross-block contribution of a diagonal block.

    For C[block x block] = A[block x block]·B[block x block]
    + A[block x K]·B[K x block] where K is the complement, this produces
    the |block|²·|K| rank-1 terms of the second summand.
    """
    K = [k for k in range(N) if k not in block]
    rank = len(block) * len(block) * len(K)

    def factors_fn():
        out = []
        for r1 in block:
            for c1 in block:
                for k in K:
                    out.append([_E(N, r1, k), _E(N, k, c1), _E(N, r1, c1)])
        return out

    return Decomposition(
        f"cross_terms({sorted(block)} in {N}x{N})", n=N, rank=rank,
        factors_fn=factors_fn,
        description=f"Cross-block rank-1 terms for block {sorted(block)}",
        construction={
            "op": "border_terms", "n": N, "rank": rank,
            "note": f"cross-block A[block x K]·B[K x block] terms for block {sorted(block)}",
        },
    )


def _block_composition(D: Decomposition, N: int, block: list[int]) -> Decomposition:
    """Compose a registry decomposition into a diagonal block of an N×N problem.

    Embeds D at rows=cols=block, adds cross-block rank-1 terms, and naive-fills
    the remaining outputs. Valid because a diagonal block of C = A·B splits as
    C[block x block] = A[block x block]·B[block x block] + A[block x K]·B[K x block].
    """
    assert D.n == len(block)
    covered = {(r, c) for r in block for c in block}
    return direct_sum(
        block_embed(D, N, list(block), list(block)),
        _cross_terms(N, list(block)),
        naive_fill(N, covered),
    )


# ---------------------------------------------------------------------------
# The rank-26 construction, expressed as a composition
# ---------------------------------------------------------------------------

def block26_composition() -> Decomposition:
    """Rank-26 3×3 via 2+1 block split, as a composition.

    C11 (rows/cols {0,1}): Strassen 7 + naive 4 for a12·b21ᵀ contribution
    C12, C21, c22: naive fills for the border outputs.
    """
    N = 3
    # Strassen on the 2×2 block at rows/cols {0,1} → covers C11 outputs
    strassen_block = block_embed(STRASSEN_2X2, N, [0, 1], [0, 1])

    # The a12·b21ᵀ term: 4 naive triples writing to C11
    # (these are rank-1: U=E(i,2), V=E(2,j), W=E(i,j) for i,j in {0,1})
    def border_c11_fn():
        out = []
        for i in (0, 1):
            for j in (0, 1):
                out.append([_E(N, i, 2), _E(N, 2, j), _E(N, i, j)])
        return out

    border_c11 = Decomposition(
        "border-c11", n=N, rank=4, factors_fn=border_c11_fn,
        description="a12·b21ᵀ rank-1 terms for C11",
        construction={
            "op": "border_terms", "n": N, "rank": 4,
            "note": "a12·b21ᵀ rank-1 terms for the C11 block",
        },
    )

    # All other outputs via naive fill
    covered = {(e, f) for e in (0, 1) for f in (0, 1)}  # C11 done
    borders = naive_fill(N, covered)

    return direct_sum(strassen_block, border_c11, borders)


# ---------------------------------------------------------------------------
# Composition search
# ---------------------------------------------------------------------------

def search_compositions(n, max_rank, time_budget_secs, seed=0):
    """Search operator applications over the registry for an n×n decomposition.

    Enumerates three families of candidates:
    1. Registry entries with dimension n (e.g. laderman-23 for n=3).
    2. Tensor products of registry pairs whose dimensions double to n
       (e.g. Strassen ⊗ Strassen gives rank 49 for n=4).
    3. Block compositions: for each registry decomposition of dimension
       m < n and each m-sized index subset, embed it in a diagonal block,
       add cross-block rank-1 terms, and naive-fill the remaining outputs
       (this family contains the rank-26 2+1 construction for n=3).

    Every candidate with rank <= max_rank is verified with the exact
    tensor-identity checker. Returns a list of (rank, decomposition)
    sorted by rank, then name. Enumeration order is shuffled with the
    given seed so a partial budget still covers diverse candidates.
    Stops generating and verifying new candidates once the budget expires.
    """
    deadline = time.monotonic() + time_budget_secs
    rng = random.Random(seed)
    results = []
    seen = set()

    def consider(decomp):
        """Verify a candidate if within rank and budget. Returns False on timeout."""
        if decomp.rank > max_rank:
            return True
        key = (decomp.rank, decomp.name)
        if key in seen:
            return True
        seen.add(key)
        if time.monotonic() >= deadline:
            return False
        if check(decomp.factors(), n)["feasible"]:
            results.append((decomp.rank, decomp))
        return True

    candidates = []

    # 1. Registry entries at dimension n.
    for decomp in REGISTRY.values():
        if decomp.n == n:
            candidates.append(decomp)

    # 2. Tensor products of equal-dimension registry pairs doubling to n.
    registry = list(REGISTRY.values())
    for i, A in enumerate(registry):
        for B in registry[i:]:
            if A.n == B.n and 2 * A.n == n:
                candidates.append(tensor_product(A, B))

    # 3. Block compositions over registry decompositions of dimension m < n.
    for m in range(2, n):
        for D in registry:
            if D.n != m:
                continue
            cross = m * m * (n - m)
            fill = (n * n - m * m) * n
            if D.rank + cross + fill > max_rank:
                continue
            for block in itertools.combinations(range(n), m):
                candidates.append(_block_composition(D, n, list(block)))

    rng.shuffle(candidates)
    for decomp in candidates:
        if not consider(decomp):
            break

    results.sort(key=lambda t: (t[0], t[1].name))
    return results


if __name__ == "__main__":
    print("Laderman-23 exact verification:", check(LADERMAN_23.factors(), 3)["feasible"])
    found3 = search_compositions(3, 26, 120, seed=0)
    print("n=3 search (max_rank=26):", [(r, d.name) for r, d in found3])
    found4 = search_compositions(4, 49, 120, seed=0)
    print("n=4 search (max_rank=49):", [(r, d.name) for r, d in found4])
    if found3:
        print()
        print("Construction of best n=3 result:")
        print(found3[0][1].describe_construction())
