"""Minimal pure-Python QR code encoder (byte mode, error correction M, versions 1-10: up to 213 bytes).

Enough for a URL + pairing code. Renders to text (terminal), SVG (web page) or a module matrix.
    m = encode("https://example.ts.net/connect?pair=abc")   # list of rows of bool (True = dark)
    print(to_text(m)); svg = to_svg(m)
"""
from __future__ import annotations

# (ec codewords per block, [(number of blocks, data codewords per block), ...]) for level M
_BLOCKS_M = {1: (10, [(1, 16)]), 2: (16, [(1, 28)]), 3: (26, [(1, 44)]), 4: (18, [(2, 32)]),
             5: (24, [(2, 43)]), 6: (16, [(4, 27)]), 7: (18, [(4, 31)]), 8: (22, [(2, 38), (2, 39)]),
             9: (22, [(3, 36), (2, 37)]), 10: (26, [(4, 43), (1, 44)])}
_ALIGN = {1: [], 2: [6, 18], 3: [6, 22], 4: [6, 26], 5: [6, 30], 6: [6, 34], 7: [6, 22, 38],
          8: [6, 24, 42], 9: [6, 26, 46], 10: [6, 28, 50]}
_REMAINDER = {1: 0, 2: 7, 3: 7, 4: 7, 5: 7, 6: 7, 7: 0, 8: 0, 9: 0, 10: 0}
MAX_BYTES = 213

# GF(256) with the QR polynomial 0x11D
_EXP = [0] * 512
_LOG = [0] * 256
_x = 1
for _i in range(255):
    _EXP[_i] = _x
    _LOG[_x] = _i
    _x <<= 1
    if _x & 0x100:
        _x ^= 0x11D
for _i in range(255, 512):
    _EXP[_i] = _EXP[_i - 255]


def _gf_mul(a: int, b: int) -> int:
    return 0 if a == 0 or b == 0 else _EXP[_LOG[a] + _LOG[b]]


def _rs_ec(data: list[int], n: int) -> list[int]:
    gen = [1]
    for i in range(n):
        nxt = [0] * (len(gen) + 1)
        for j, c in enumerate(gen):
            nxt[j] ^= c
            nxt[j + 1] ^= _gf_mul(c, _EXP[i])
        gen = nxt
    rem = list(data) + [0] * n
    for i in range(len(data)):
        coef = rem[i]
        if coef:
            for j in range(1, len(gen)):
                rem[i + j] ^= _gf_mul(gen[j], coef)
    return rem[len(data):]


def _capacity(v: int) -> int:
    return sum(nb * nd for nb, nd in _BLOCKS_M[v][1])


def _codewords(data: bytes) -> tuple[int, list[int]]:
    for v in range(1, 11):
        count_bits = 8 if v < 10 else 16
        cap = _capacity(v)
        if 4 + count_bits + 8 * len(data) <= cap * 8:
            break
    else:
        raise ValueError(f"QR: text too long ({len(data)} bytes, max {MAX_BYTES})")
    bits: list[int] = []

    def put(value: int, n: int) -> None:
        bits.extend((value >> (n - 1 - i)) & 1 for i in range(n))
    put(0b0100, 4)
    put(len(data), count_bits)
    for b in data:
        put(b, 8)
    put(0, min(4, cap * 8 - len(bits)))
    while len(bits) % 8:
        bits.append(0)
    words = [int("".join(map(str, bits[i:i + 8])), 2) for i in range(0, len(bits), 8)]
    pad = (0xEC, 0x11)
    i = 0
    while len(words) < cap:
        words.append(pad[i % 2])
        i += 1
    ec_n, groups = _BLOCKS_M[v]
    blocks, pos = [], 0
    for nb, nd in groups:
        for _ in range(nb):
            blocks.append(words[pos:pos + nd])
            pos += nd
    ecs = [_rs_ec(b, ec_n) for b in blocks]
    out = []
    for i in range(max(len(b) for b in blocks)):
        out.extend(b[i] for b in blocks if i < len(b))
    for i in range(ec_n):
        out.extend(e[i] for e in ecs)
    return v, out


def _bch(value: int, poly: int, bits: int) -> int:
    v = value << bits
    plen = poly.bit_length()
    while v.bit_length() >= plen:
        v ^= poly << (v.bit_length() - plen)
    return (value << bits) | v


_MASKS = [lambda r, c: (r + c) % 2 == 0, lambda r, c: r % 2 == 0, lambda r, c: c % 3 == 0,
          lambda r, c: (r + c) % 3 == 0, lambda r, c: (r // 2 + c // 3) % 2 == 0,
          lambda r, c: (r * c) % 2 + (r * c) % 3 == 0, lambda r, c: ((r * c) % 2 + (r * c) % 3) % 2 == 0,
          lambda r, c: ((r + c) % 2 + (r * c) % 3) % 2 == 0]


def _base(v: int) -> tuple[list[list[int | None]], list[list[bool]]]:
    n = 17 + 4 * v
    m: list[list[int | None]] = [[None] * n for _ in range(n)]
    fixed = [[False] * n for _ in range(n)]

    def setm(r: int, c: int, val: int) -> None:
        m[r][c] = val
        fixed[r][c] = True
    for r0, c0 in ((0, 0), (0, n - 7), (n - 7, 0)):
        for r in range(-1, 8):
            for c in range(-1, 8):
                rr, cc = r0 + r, c0 + c
                if 0 <= rr < n and 0 <= cc < n:
                    dark = (0 <= r <= 6 and 0 <= c <= 6 and (r in (0, 6) or c in (0, 6) or (2 <= r <= 4 and 2 <= c <= 4)))
                    setm(rr, cc, 1 if dark else 0)
    for i in range(8, n - 8):
        setm(6, i, 1 if i % 2 == 0 else 0)
        setm(i, 6, 1 if i % 2 == 0 else 0)
    pos = _ALIGN[v]
    for r in pos:
        for c in pos:
            if (r, c) in ((pos[0], pos[0]), (pos[0], pos[-1]), (pos[-1], pos[0])):
                continue                   # would overlap a finder pattern
            for dr in range(-2, 3):
                for dc in range(-2, 3):
                    setm(r + dr, c + dc, 1 if max(abs(dr), abs(dc)) != 1 else 0)
    setm(n - 8, 8, 1)                      # dark module
    for i in range(9):                     # reserve format areas
        for (r, c) in ((8, i), (i, 8)):
            if not fixed[r][c]:
                setm(r, c, 0)
    for i in range(8):
        setm(8, n - 1 - i, 0)
        setm(n - 1 - i, 8, 0)
    if v >= 7:
        for i in range(6):
            for j in range(3):
                setm(i, n - 11 + j, 0)
                setm(n - 11 + j, i, 0)
    return m, fixed


def _place(m: list[list[int | None]], fixed: list[list[bool]], words: list[int], rem: int) -> None:
    n = len(m)
    bits = [(w >> (7 - i)) & 1 for w in words for i in range(8)] + [0] * rem
    k = 0
    col = n - 1
    upward = True
    while col > 0:
        if col == 6:
            col -= 1
        rows = range(n - 1, -1, -1) if upward else range(n)
        for r in rows:
            for c in (col, col - 1):
                if not fixed[r][c]:
                    m[r][c] = bits[k] if k < len(bits) else 0
                    k += 1
        upward = not upward
        col -= 2


def _format_bits(mask: int) -> int:
    return _bch((0b00 << 3) | mask, 0x537, 10) ^ 0x5412     # level M = 00


def _apply(m, fixed, mask: int, v: int) -> list[list[int]]:
    n = len(m)
    out = [[(m[r][c] ^ (1 if (not fixed[r][c] and _MASKS[mask](r, c)) else 0)) for c in range(n)] for r in range(n)]
    f = _format_bits(mask)
    fb = [(f >> i) & 1 for i in range(15)]          # bit 0 = least significant
    # around the top-left finder
    for i in range(6):
        out[i][8] = fb[i]
    out[7][8] = fb[6]
    out[8][8] = fb[7]
    out[8][7] = fb[8]
    for i in range(9, 15):
        out[8][14 - i] = fb[i]
    # split copy
    for i in range(8):
        out[8][n - 1 - i] = fb[i]
    for i in range(8, 15):
        out[n - 15 + i][8] = fb[i]
    out[n - 8][8] = 1
    if v >= 7:
        vb = _bch(v, 0x1F25, 12)
        for i in range(18):
            bit = (vb >> i) & 1
            a, b = i // 3, n - 11 + i % 3
            out[a][b] = bit
            out[b][a] = bit
    return out


def _penalty(m: list[list[int]]) -> int:
    n = len(m)
    score = 0
    for grid in (m, [list(col) for col in zip(*m)]):
        for row in grid:
            run, prev = 1, row[0]
            for x in row[1:]:
                if x == prev:
                    run += 1
                else:
                    if run >= 5:
                        score += run - 2
                    run, prev = 1, x
            if run >= 5:
                score += run - 2
            s = "".join(map(str, row))
            for pat in ("10111010000", "00001011101"):
                start = s.find(pat)
                while start != -1:
                    score += 40
                    start = s.find(pat, start + 1)
    for r in range(n - 1):
        for c in range(n - 1):
            v = m[r][c]
            if v == m[r][c + 1] == m[r + 1][c] == m[r + 1][c + 1]:
                score += 3
    dark = sum(map(sum, m))
    pct = dark * 100 / (n * n)
    score += int(abs(pct - 50) // 5) * 10
    return score


def encode(text: str) -> list[list[bool]]:
    """QR code (byte mode, level M) for `text` as rows of booleans (True = dark), without quiet zone."""
    v, words = _codewords(text.encode("utf-8"))
    base, fixed = _base(v)
    _place(base, fixed, words, _REMAINDER[v])
    best = min((_apply(base, fixed, k, v) for k in range(8)), key=_penalty)
    return [[bool(x) for x in row] for row in best]


def to_text(m: list[list[bool]], quiet: int = 2, ansi: bool = True) -> str:
    """Two rows per line with half blocks. ansi=True forces black on white (works on dark terminals)."""
    n = len(m)
    size = n + 2 * quiet

    def dark(r: int, c: int) -> bool:
        r, c = r - quiet, c - quiet
        return 0 <= r < n and 0 <= c < n and m[r][c]
    lines = []
    for r in range(0, size, 2):
        chars = []
        for c in range(size):
            top, bottom = dark(r, c), dark(r + 1, c) if r + 1 < size else False
            chars.append("█" if top and bottom else "▀" if top else "▄" if bottom else " ")
        line = "".join(chars)
        lines.append(f"\x1b[30;47m{line}\x1b[0m" if ansi else line)
    return "\n".join(lines)


def to_svg(m: list[list[bool]], scale: int = 8, quiet: int = 4) -> str:
    n = len(m)
    size = (n + 2 * quiet) * scale
    path = "".join(f"M{(c + quiet) * scale},{(r + quiet) * scale}h{scale}v{scale}h-{scale}z"
                   for r in range(n) for c in range(n) if m[r][c])
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}" width="{size}" height="{size}" '
            f'shape-rendering="crispEdges"><rect width="100%" height="100%" fill="#fff"/>'
            f'<path d="{path}" fill="#000"/></svg>')
