#!/usr/bin/env python3
"""Laderman's 1976 rank-23 3x3 matrix multiplication decomposition.

Transcribed from Courtois et al., "A New General-Purpose Method to Multiply
3x3 Matrices Using Only 23 Multiplications" (arXiv:1108.2830), section 2.4,
which presents Laderman's solution in Maple-verifiable form.

Each P_i = (linear form in A) * (linear form in B), and C[e][f] is a signed
sum of the P_i. Triple i = (U_i, V_i, W_i) where U_i, V_i are the coefficient
matrices of the two linear forms and W_i[e][f] is the coefficient of P_i
in C[e][f].
"""
import sys
sys.path.insert(0, '/home/hatch/workspace/discovery-loop/problems/matrix_multiplication')
from verify import check


def M(entries):
    """Build a 3x3 matrix from a dict {(r,c): val} (0-based)."""
    m = [[0]*3 for _ in range(3)]
    for (r, c), v in entries.items():
        m[r][c] = v
    return m


# Each entry: (U_entries, V_entries, W_entries) as dicts
# Transcribed from P01..P23 and the 9 output expansions in arXiv:1108.2830.
RAW = [
    # P01 := (a11-a12-a13+a21-a22-a32-a33) * (-b22);  c12 += P01
    ({(0,0):1,(0,1):-1,(0,2):-1,(1,0):1,(1,1):-1,(2,1):-1,(2,2):-1},
     {(1,1):-1},
     {(0,1):1}),
    # P02 := (a11+a21) * (b12+b22);  c21 += P02; c22 += P02
    ({(0,0):1,(1,0):1},
     {(0,1):1,(1,1):1},
     {(1,0):1,(1,1):1}),
    # P03 := (a22) * (b11-b12+b21-b22-b23+b31-b33);  c21 += P03
    ({(1,1):1},
     {(0,0):1,(0,1):-1,(1,0):1,(1,1):-1,(1,2):-1,(2,0):1,(2,2):-1},
     {(1,0):1}),
    # P04 := (-a11-a21+a22) * (-b11+b12+b22);  c12 -= P04; c21 += P04; c22 += P04
    ({(0,0):-1,(1,0):-1,(1,1):1},
     {(0,0):-1,(0,1):1,(1,1):1},
     {(0,1):-1,(1,0):1,(1,1):1}),
    # P05 := (-a21+a22) * (-b11+b12);  c12 += P05; c22 -= P05
    ({(1,0):-1,(1,1):1},
     {(0,0):-1,(0,1):1},
     {(0,1):1,(1,1):-1}),
    # P06 := (a11) * (-b11);  c11 -= P06; c12 -= P06; c13 -= P06; c21 += P06; c22 += P06; c31 += P06; c33 += P06
    ({(0,0):1},
     {(0,0):-1},
     {(0,0):-1,(0,1):-1,(0,2):-1,(1,0):1,(1,1):1,(2,0):1,(2,2):1}),
    # P07 := (a11+a31+a32) * (b11-b13+b23);  c13 -= P07; c31 += P07; c33 += P07
    ({(0,0):1,(2,0):1,(2,1):1},
     {(0,0):1,(0,2):-1,(1,2):1},
     {(0,2):-1,(2,0):1,(2,2):1}),
    # P08 := (a11+a31) * (-b13+b23);  c31 -= P08; c33 -= P08
    ({(0,0):1,(2,0):1},
     {(0,2):-1,(1,2):1},
     {(2,0):-1,(2,2):-1}),
    # P09 := (a31+a32) * (b11-b13);  c13 += P09; c33 -= P09
    ({(2,0):1,(2,1):1},
     {(0,0):1,(0,2):-1},
     {(0,2):1,(2,2):-1}),
    # P10 := (a11+a12-a13-a22+a23+a31+a32) * (b23);  c13 += P10
    ({(0,0):1,(0,1):1,(0,2):-1,(1,1):-1,(1,2):1,(2,0):1,(2,1):1},
     {(1,2):1},
     {(0,2):1}),
    # P11 := (a32) * (-b11+b13+b21-b22-b23-b31+b32);  c31 += P11
    ({(2,1):1},
     {(0,0):-1,(0,2):1,(1,0):1,(1,1):-1,(1,2):-1,(2,0):-1,(2,1):1},
     {(2,0):1}),
    # P12 := (a13+a32+a33) * (b22+b31-b32);  c12 -= P12; c31 += P12; c32 += P12
    ({(0,2):1,(2,1):1,(2,2):1},
     {(1,1):1,(2,0):1,(2,1):-1},
     {(0,1):-1,(2,0):1,(2,1):1}),
    # P13 := (a13+a33) * (-b22+b32);  c31 += P13; c32 += P13
    ({(0,2):1,(2,2):1},
     {(1,1):-1,(2,1):1},
     {(2,0):1,(2,1):1}),
    # P14 := (a13) * (b31);  c11 += P14; c12 += P14; c13 += P14; c21 += P14; c23 += P14; c31 -= P14; c32 -= P14
    ({(0,2):1},
     {(2,0):1},
     {(0,0):1,(0,1):1,(0,2):1,(1,0):1,(1,2):1,(2,0):-1,(2,1):-1}),
    # P15 := (-a32-a33) * (-b31+b32);  c12 += P15; c32 -= P15
    ({(2,1):-1,(2,2):-1},
     {(2,0):-1,(2,1):1},
     {(0,1):1,(2,1):-1}),
    # P16 := (a13+a22-a23) * (b23-b31+b33);  c13 += P16; c21 += P16; c23 += P16
    ({(0,2):1,(1,1):1,(1,2):-1},
     {(1,2):1,(2,0):-1,(2,2):1},
     {(0,2):1,(1,0):1,(1,2):1}),
    # P17 := (-a13+a23) * (b23+b33);  c21 += P17; c23 += P17
    ({(0,2):-1,(1,2):1},
     {(1,2):1,(2,2):1},
     {(1,0):1,(1,2):1}),
    # P18 := (a22-a23) * (b31-b33);  c13 += P18; c23 += P18
    ({(1,1):1,(1,2):-1},
     {(2,0):1,(2,2):-1},
     {(0,2):1,(1,2):1}),
    # P19 := (a12) * (b21);  c11 += P19
    ({(0,1):1},
     {(1,0):1},
     {(0,0):1}),
    # P20 := (a23) * (b32);  c22 += P20
    ({(1,2):1},
     {(2,1):1},
     {(1,1):1}),
    # P21 := (a21) * (b13);  c23 += P21
    ({(1,0):1},
     {(0,2):1},
     {(1,2):1}),
    # P22 := (a31) * (b12);  c32 += P22
    ({(2,0):1},
     {(0,1):1},
     {(2,1):1}),
    # P23 := (a33) * (b33);  c33 += P23
    ({(2,2):1},
     {(2,2):1},
     {(2,2):1}),
]


def laderman():
    return [[M(u), M(v), M(w)] for (u, v, w) in RAW]


if __name__ == '__main__':
    fac = laderman()
    result = check(fac, 3)
    print("Laderman rank-23 verification:", result)
    print()
    print("Sparsity analysis (nonzeros per factor matrix):")
    max_nz = 0
    dist = {}
    for i, (u, v, w) in enumerate(fac):
        nz_u = sum(1 for row in u for x in row if x != 0)
        nz_v = sum(1 for row in v for x in row if x != 0)
        nz_w = sum(1 for row in w for x in row if x != 0)
        m = max(nz_u, nz_v, nz_w)
        max_nz = max(max_nz, m)
        dist[m] = dist.get(m, 0) + 1
        print(f"  triple {i+1:2d}: U={nz_u} V={nz_v} W={nz_w} max={m}")
    print(f"\nMax nonzeros in any factor matrix: {max_nz}")
    print(f"Distribution of per-triple max: {dict(sorted(dist.items()))}")
