"""Composition engine for matrix-multiplication discovery.

Instead of searching over individual {-1,0,1} matrix entries, search over
COMPOSITIONS of known decompositions. This is the structural insight the
nightly loop stumbled into with the 2+1 block construction (rank 26):
it composed Strassen (for the 2x2 block) with naive (for the borders).

A Decomposition is a named bilinear algorithm. Operators combine them:
- tensor_product(A, B): rank multiplies, dimension doubles (Strassen recursion)
- block_embed(A, n, rows, cols): embed an n×n decomposition at specific indices
- direct_sum(*parts): concatenate for disjoint outputs (the block26 trick)
- naive_fill(n, covered): naive triples for outputs not yet covered

The search space is compositions, not matrix entries. Much smaller, much smarter.
"""

from __future__ import annotations


def _E(n, i, j, s=1):
    m = [[0] * n for _ in range(n)]
    m[i][j] = s
    return m


def _add(n, *terms):
    m = [[0] * n for _ in range(n)]
    for (i, j, s) in terms:
        m[i][j] += s
    return m


class Decomposition:
    """A named bilinear algorithm for n×n matrix multiplication."""

    def __init__(self, name, n, rank, factors_fn, description=""):
        self.name = name
        self.n = n
        self.rank = rank
        self._factors_fn = factors_fn
        self.description = description

    def factors(self):
        f = self._factors_fn()
        assert len(f) == self.rank, f"{self.name}: expected {self.rank}, got {len(f)}"
        return f

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


# ---------------------------------------------------------------------------
# Library of known decompositions
# ---------------------------------------------------------------------------

STRASSEN_2X2 = Decomposition(
    "strassen-2x2", n=2, rank=7,
    factors_fn=_strassen_2x2_factors,
    description="Strassen 1969, proven optimal by Winograd 1971",
)

NAIVE_2X2 = Decomposition(
    "naive-2x2", n=2, rank=8,
    factors_fn=lambda: _naive_factors(2),
    description="Naive O(n^3)",
)

NAIVE_3X3 = Decomposition(
    "naive-3x3", n=3, rank=27,
    factors_fn=lambda: _naive_factors(3),
    description="Naive O(n^3)",
)

LIBRARY = {
    "strassen-2x2": STRASSEN_2X2,
    "naive-2x2": NAIVE_2X2,
    "naive-3x3": NAIVE_3X3,
}


# ---------------------------------------------------------------------------
# Composition operators
# ---------------------------------------------------------------------------

def tensor_product(A: Decomposition, B: Decomposition) -> Decomposition:
    """Bilinear algorithm for 2n×2n from n×n algorithms. Rank multiplies."""
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

    border_c11 = Decomposition("border-c11", n=N, rank=4, factors_fn=border_c11_fn,
                               description="a12·b21ᵀ rank-1 terms for C11")

    # All other outputs via naive fill
    covered = {(e, f) for e in (0, 1) for f in (0, 1)}  # C11 done
    borders = naive_fill(N, covered)

    return direct_sum(strassen_block, border_c11, borders)
