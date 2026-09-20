"""Independent checker for truncated-digest collisions on the salted proxy targets.

Truncated collisions measure search machinery only; they are not partial progress toward a full collision.

A candidate is two hex messages m1 != m2, each 1..64 bytes. The checked claim is
``digest(f, salt || m1)[:bits] == digest(f, salt || m2)[:bits]`` with the salt, the function and the
truncation width read from records.json. Everything here recomputes the claim from public target data;
nothing from the candidate is trusted beyond the two messages.

Three digest backends live here so the worker needs no extra package:
  * ``sha256``          -- hashlib
  * ``ripemd160``       -- ``hashlib.new("ripemd160")`` when OpenSSL still exposes it, otherwise the pure
                           Python implementation below (``ripemd160_python``), which is tested against the
                           published vectors
  * ``sha256-reduced``  -- ``sha256_rounds(data, rounds)``, a pure Python SHA-256 whose compression loop stops
                           after ``rounds`` steps; at rounds=64 it equals hashlib.sha256

    python verify.py candidate.json      # {"target": name, "m1": hex, "m2": hex}
"""

import hashlib
import json
import os
import sys

if __package__:
    from . import records
else:  # direct ``python problems/hash_collision_prize/verify.py`` compatibility
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    from problems.hash_collision_prize import records


MASK32 = 0xFFFFFFFF
MAX_MESSAGE_BYTES = 64
FUNCTIONS = ("sha256", "ripemd160", "sha256-reduced")

_SHA256_K = (
    0x428A2F98,
    0x71374491,
    0xB5C0FBCF,
    0xE9B5DBA5,
    0x3956C25B,
    0x59F111F1,
    0x923F82A4,
    0xAB1C5ED5,
    0xD807AA98,
    0x12835B01,
    0x243185BE,
    0x550C7DC3,
    0x72BE5D74,
    0x80DEB1FE,
    0x9BDC06A7,
    0xC19BF174,
    0xE49B69C1,
    0xEFBE4786,
    0x0FC19DC6,
    0x240CA1CC,
    0x2DE92C6F,
    0x4A7484AA,
    0x5CB0A9DC,
    0x76F988DA,
    0x983E5152,
    0xA831C66D,
    0xB00327C8,
    0xBF597FC7,
    0xC6E00BF3,
    0xD5A79147,
    0x06CA6351,
    0x14292967,
    0x27B70A85,
    0x2E1B2138,
    0x4D2C6DFC,
    0x53380D13,
    0x650A7354,
    0x766A0ABB,
    0x81C2C92E,
    0x92722C85,
    0xA2BFE8A1,
    0xA81A664B,
    0xC24B8B70,
    0xC76C51A3,
    0xD192E819,
    0xD6990624,
    0xF40E3585,
    0x106AA070,
    0x19A4C116,
    0x1E376C08,
    0x2748774C,
    0x34B0BCB5,
    0x391C0CB3,
    0x4ED8AA4A,
    0x5B9CCA4F,
    0x682E6FF3,
    0x748F82EE,
    0x78A5636F,
    0x84C87814,
    0x8CC70208,
    0x90BEFFFA,
    0xA4506CEB,
    0xBEF9A3F7,
    0xC67178F2,
)
_SHA256_H = (
    0x6A09E667,
    0xBB67AE85,
    0x3C6EF372,
    0xA54FF53A,
    0x510E527F,
    0x9B05688C,
    0x1F83D9AB,
    0x5BE0CD19,
)


def _rotr32(x, n):
    return ((x >> n) | (x << (32 - n))) & MASK32


def _rotl32(x, n):
    return ((x << n) | (x >> (32 - n))) & MASK32


def _pad_be(data):
    """SHA-2 style padding: 0x80, zeros, then the 64-bit big-endian bit length."""
    bit_length = len(data) * 8
    padded = bytes(data) + b"\x80"
    padded += b"\x00" * ((56 - len(padded) % 64) % 64)
    return padded + bit_length.to_bytes(8, "big")


def sha256_rounds(data, rounds=64):
    """Pure Python SHA-256 truncated to ``rounds`` compression steps (1..64); rounds=64 == hashlib.sha256."""
    if isinstance(rounds, bool) or not isinstance(rounds, int) or not 1 <= rounds <= 64:
        raise ValueError(f"rounds must be an integer in 1..64, got {rounds!r}")
    state = list(_SHA256_H)
    message = _pad_be(data)
    for offset in range(0, len(message), 64):
        block = message[offset : offset + 64]
        w = [int.from_bytes(block[i * 4 : i * 4 + 4], "big") for i in range(16)]
        for i in range(16, rounds):
            s0 = _rotr32(w[i - 15], 7) ^ _rotr32(w[i - 15], 18) ^ (w[i - 15] >> 3)
            s1 = _rotr32(w[i - 2], 17) ^ _rotr32(w[i - 2], 19) ^ (w[i - 2] >> 10)
            w.append((w[i - 16] + s0 + w[i - 7] + s1) & MASK32)
        a, b, c, d, e, f, g, h = state
        for i in range(rounds):
            s1 = _rotr32(e, 6) ^ _rotr32(e, 11) ^ _rotr32(e, 25)
            ch = (e & f) ^ ((~e & MASK32) & g)
            t1 = (h + s1 + ch + _SHA256_K[i] + w[i]) & MASK32
            s0 = _rotr32(a, 2) ^ _rotr32(a, 13) ^ _rotr32(a, 22)
            maj = (a & b) ^ (a & c) ^ (b & c)
            t2 = (s0 + maj) & MASK32
            h, g, f, e, d, c, b, a = g, f, e, (d + t1) & MASK32, c, b, a, (t1 + t2) & MASK32
        state = [(x + y) & MASK32 for x, y in zip(state, (a, b, c, d, e, f, g, h))]
    return b"".join(x.to_bytes(4, "big") for x in state)


_RMD_RL = (
    0,
    1,
    2,
    3,
    4,
    5,
    6,
    7,
    8,
    9,
    10,
    11,
    12,
    13,
    14,
    15,
    7,
    4,
    13,
    1,
    10,
    6,
    15,
    3,
    12,
    0,
    9,
    5,
    2,
    14,
    11,
    8,
    3,
    10,
    14,
    4,
    9,
    15,
    8,
    1,
    2,
    7,
    0,
    6,
    13,
    11,
    5,
    12,
    1,
    9,
    11,
    10,
    0,
    8,
    12,
    4,
    13,
    3,
    7,
    15,
    14,
    5,
    6,
    2,
    4,
    0,
    5,
    9,
    7,
    12,
    2,
    10,
    14,
    1,
    3,
    8,
    11,
    6,
    15,
    13,
)
_RMD_RR = (
    5,
    14,
    7,
    0,
    9,
    2,
    11,
    4,
    13,
    6,
    15,
    8,
    1,
    10,
    3,
    12,
    6,
    11,
    3,
    7,
    0,
    13,
    5,
    10,
    14,
    15,
    8,
    12,
    4,
    9,
    1,
    2,
    15,
    5,
    1,
    3,
    7,
    14,
    6,
    9,
    11,
    8,
    12,
    2,
    10,
    0,
    4,
    13,
    8,
    6,
    4,
    1,
    3,
    11,
    15,
    0,
    5,
    12,
    2,
    13,
    9,
    7,
    10,
    14,
    12,
    15,
    10,
    4,
    1,
    5,
    8,
    7,
    6,
    2,
    13,
    14,
    0,
    3,
    9,
    11,
)
_RMD_SL = (
    11,
    14,
    15,
    12,
    5,
    8,
    7,
    9,
    11,
    13,
    14,
    15,
    6,
    7,
    9,
    8,
    7,
    6,
    8,
    13,
    11,
    9,
    7,
    15,
    7,
    12,
    15,
    9,
    11,
    7,
    13,
    12,
    11,
    13,
    6,
    7,
    14,
    9,
    13,
    15,
    14,
    8,
    13,
    6,
    5,
    12,
    7,
    5,
    11,
    12,
    14,
    15,
    14,
    15,
    9,
    8,
    9,
    14,
    5,
    6,
    8,
    6,
    5,
    12,
    9,
    15,
    5,
    11,
    6,
    8,
    13,
    12,
    5,
    12,
    13,
    14,
    11,
    8,
    5,
    6,
)
_RMD_SR = (
    8,
    9,
    9,
    11,
    13,
    15,
    15,
    5,
    7,
    7,
    8,
    11,
    14,
    14,
    12,
    6,
    9,
    13,
    15,
    7,
    12,
    8,
    9,
    11,
    7,
    7,
    12,
    7,
    6,
    15,
    13,
    11,
    9,
    7,
    15,
    11,
    8,
    6,
    6,
    14,
    12,
    13,
    5,
    14,
    13,
    13,
    7,
    5,
    15,
    5,
    8,
    11,
    14,
    14,
    6,
    14,
    6,
    9,
    12,
    9,
    12,
    5,
    15,
    8,
    8,
    5,
    12,
    9,
    12,
    5,
    14,
    6,
    8,
    13,
    6,
    5,
    15,
    13,
    11,
    11,
)
_RMD_KL = (0x00000000, 0x5A827999, 0x6ED9EBA1, 0x8F1BBCDC, 0xA953FD4E)
_RMD_KR = (0x50A28BE6, 0x5C4DD124, 0x6D703EF3, 0x7A6D76E9, 0x00000000)
_RMD_H = (0x67452301, 0xEFCDAB89, 0x98BADCFE, 0x10325476, 0xC3D2E1F0)


def _rmd_f(j, x, y, z):
    if j < 16:
        return x ^ y ^ z
    if j < 32:
        return (x & y) | ((~x & MASK32) & z)
    if j < 48:
        return (x | (~y & MASK32)) ^ z
    if j < 64:
        return (x & z) | (y & (~z & MASK32))
    return x ^ (y | (~z & MASK32))


def ripemd160_python(data):
    """Pure Python RIPEMD-160 (RFC-equivalent), used when OpenSSL no longer ships the algorithm."""
    state = list(_RMD_H)
    bit_length = len(data) * 8
    message = bytes(data) + b"\x80"
    message += b"\x00" * ((56 - len(message) % 64) % 64)
    message += bit_length.to_bytes(8, "little")
    for offset in range(0, len(message), 64):
        block = message[offset : offset + 64]
        x = [int.from_bytes(block[i * 4 : i * 4 + 4], "little") for i in range(16)]
        a, b, c, d, e = state
        aa, bb, cc, dd, ee = state
        for j in range(80):
            t = (a + _rmd_f(j, b, c, d) + x[_RMD_RL[j]] + _RMD_KL[j // 16]) & MASK32
            t = (_rotl32(t, _RMD_SL[j]) + e) & MASK32
            a, e, d, c, b = e, d, _rotl32(c, 10), b, t
            t = (aa + _rmd_f(79 - j, bb, cc, dd) + x[_RMD_RR[j]] + _RMD_KR[j // 16]) & MASK32
            t = (_rotl32(t, _RMD_SR[j]) + ee) & MASK32
            aa, ee, dd, cc, bb = ee, dd, _rotl32(cc, 10), bb, t
        state = [
            (state[1] + c + dd) & MASK32,
            (state[2] + d + ee) & MASK32,
            (state[3] + e + aa) & MASK32,
            (state[4] + a + bb) & MASK32,
            (state[0] + b + cc) & MASK32,
        ]
    return b"".join(x.to_bytes(4, "little") for x in state)


def _hashlib_ripemd160_available():
    try:
        hashlib.new("ripemd160")
    except (ValueError, TypeError):
        return False
    return True


RIPEMD160_BACKEND = "hashlib" if _hashlib_ripemd160_available() else "python"


def ripemd160(data):
    """RIPEMD-160 through OpenSSL when it is present, otherwise through the pure Python fallback."""
    if RIPEMD160_BACKEND == "hashlib":
        try:
            digester = hashlib.new("ripemd160")
        except (ValueError, TypeError):
            return ripemd160_python(data)
        digester.update(bytes(data))
        return digester.digest()
    return ripemd160_python(data)


def digest(function, rounds, data):
    """Full digest of ``data`` under one of FUNCTIONS. ``rounds`` is used only by ``sha256-reduced``."""
    data = bytes(data)
    if function == "sha256":
        return hashlib.sha256(data).digest()
    if function == "ripemd160":
        return ripemd160(data)
    if function == "sha256-reduced":
        if rounds is None:
            raise ValueError("sha256-reduced requires a rounds count")
        return sha256_rounds(data, rounds)
    raise ValueError(f"unknown function {function!r} (expected one of {list(FUNCTIONS)})")


def truncated_int(data, bits):
    """The first ``bits`` bits of ``data`` read big-endian, as an integer."""
    if isinstance(bits, bool) or not isinstance(bits, int) or bits <= 0 or bits > 8 * len(data):
        raise ValueError(f"bits must be an integer in 1..{8 * len(data)}, got {bits!r}")
    width = (bits + 7) // 8
    return int.from_bytes(data[:width], "big") >> (8 * width - bits)


def prefix_hex(value, bits):
    """Truncated prefix rendered as fixed-width hex (the JSON form of ``truncated_int``)."""
    return format(value, "0{}x".format((bits + 3) // 4))


def target_digest(spec, message):
    """Truncated digest of ``salt || message`` for one target spec, as an integer."""
    payload = bytes.fromhex(spec["salt"]) + bytes(message)
    return truncated_int(digest(spec["function"], spec.get("rounds"), payload), spec["bits"])


def _message_bytes(value, label):
    if not isinstance(value, str):
        return None, f"{label} must be a hex string"
    try:
        raw = bytes.fromhex(value.strip())
    except ValueError:
        return None, f"{label} is not valid hex"
    if not 1 <= len(raw) <= MAX_MESSAGE_BYTES:
        return None, f"{label} must be 1..{MAX_MESSAGE_BYTES} bytes, got {len(raw)}"
    return raw, None


def check(m1_hex, m2_hex, target):
    """Recompute the truncated-collision claim. ``target`` is a target name or an already loaded spec."""
    spec = records.resolve(target)
    result = {"feasible": False, "reason": None, "digest_prefix": None}
    m1, reason = _message_bytes(m1_hex, "m1")
    if reason:
        result["reason"] = reason
        return result
    m2, reason = _message_bytes(m2_hex, "m2")
    if reason:
        result["reason"] = reason
        return result
    if m1 == m2:
        result["reason"] = "m1 and m2 are the same message"
        return result
    d1 = target_digest(spec, m1)
    d2 = target_digest(spec, m2)
    result["digest_prefix"] = prefix_hex(d1, spec["bits"])
    if d1 != d2:
        result["reason"] = (
            f"{spec['bits']}-bit prefixes differ: {prefix_hex(d1, spec['bits'])} != {prefix_hex(d2, spec['bits'])}"
        )
        return result
    result["feasible"] = True
    return result


if __name__ == "__main__":
    candidate = json.load(open(sys.argv[1]))
    outcome = check(candidate["m1"], candidate["m2"], candidate["target"])
    print(json.dumps(outcome))
    sys.exit(0 if outcome["feasible"] else 1)
