#!/usr/bin/env python3
"""Move-to-move autocorrelation analyzer for cutechess PGN.

Distribution metrics (p50/p99/CV) are corrupted by natural clock decay:
a smooth `spend ≈ soft(t) × constant` curve already varies across the
game without any position-driven signal. To measure whether spend
actually tracks POSITION complexity vs clock decay, we need
autocorrelation.

For each engine, per game:
  1. Extract per-move spend series.
  2. Compute lag-1 autocorrelation of raw spends.
  3. Detrend by subtracting linear fit (spend ~ a*ply + b).
  4. Compute lag-1 autocorrelation of residuals.

Interpretation:
  - HIGH raw autocorr + HIGH residual autocorr → curve-bound, no position signal
  - HIGH raw autocorr + LOW residual autocorr → spend smoothly follows clock, but
    after removing clock trend, residuals are random — neither great nor terrible
  - LOW raw autocorr + LOW residual autocorr → spend varies independently → position-aware
  - HIGH raw autocorr + NEGATIVE residual autocorr → tactical bursts vs quiet
    moves alternating (cleanest "position-aware" signature)

SF/Reckless expected: LOW residual autocorr (~0).
Coda Phase 4 v2.1 expected: HIGH residual autocorr (positive, e.g. 0.3+).
"""

import sys, re, math, argparse
from collections import defaultdict

def parse_time_spent(comment):
    m = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*(s|ms)\b", comment)
    if not m:
        return None
    v = float(m.group(1))
    return v / 1000.0 if m.group(2) == "ms" else v


def parse_games(pgn_text):
    games = re.split(r"\n\n(?=\[Event)", pgn_text)
    for g in games:
        if not g.strip():
            continue
        headers = {}
        for line in g.split("\n"):
            m = re.match(r'\[(\w+)\s+"(.*)"\]', line.strip())
            if m:
                headers[m.group(1)] = m.group(2)
        parts = g.split("\n\n", 1)
        movetext = parts[1] if len(parts) > 1 else ""
        moves = []
        for tok in re.finditer(r"(?:(\d+)\.(?:\.\.)?)?\s*(\S+?)\s*\{([^}]*)\}", movetext):
            san, comment = tok.group(2), tok.group(3)
            if san in ("1-0", "0-1", "1/2-1/2", "*"):
                continue
            t = parse_time_spent(comment)
            color = "white" if len(moves) % 2 == 0 else "black"
            moves.append((color, t))
        yield headers, moves


def autocorr_lag1(xs):
    """Lag-1 Pearson autocorrelation of a series."""
    if len(xs) < 3:
        return None
    n = len(xs)
    mean = sum(xs) / n
    var = sum((x - mean) ** 2 for x in xs)
    if var <= 0:
        return None
    cov = sum((xs[i] - mean) * (xs[i + 1] - mean) for i in range(n - 1))
    return cov / var


def linear_fit(xs):
    """Returns (a, b) such that ys[i] ≈ a*i + b."""
    n = len(xs)
    if n < 2:
        return 0.0, sum(xs) / max(1, n)
    sx = sum(range(n))
    sy = sum(xs)
    sxx = sum(i * i for i in range(n))
    sxy = sum(i * xs[i] for i in range(n))
    denom = n * sxx - sx * sx
    if denom == 0:
        return 0.0, sy / n
    a = (n * sxy - sx * sy) / denom
    b = (sy - a * sx) / n
    return a, b


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pgns", nargs="+")
    ap.add_argument("--min-moves", type=int, default=20,
                    help="skip games where engine made fewer than this many moves")
    args = ap.parse_args()

    # engine -> list of per-game (raw_autocorr, residual_autocorr, n_moves)
    engine_results = defaultdict(list)
    games_total = 0

    for pgn_path in args.pgns:
        with open(pgn_path) as f:
            pgn = f.read()
        for hdrs, moves in parse_games(pgn):
            white = hdrs.get("White")
            black = hdrs.get("Black")
            if not white or not black:
                continue
            games_total += 1
            for engine_name, color in [(white, "white"), (black, "black")]:
                spends = [t for (c, t) in moves if c == color and t is not None]
                if len(spends) < args.min_moves:
                    continue
                raw_ac = autocorr_lag1(spends)
                # Detrend: subtract linear fit
                a, b = linear_fit(spends)
                residuals = [spends[i] - (a * i + b) for i in range(len(spends))]
                resid_ac = autocorr_lag1(residuals)
                if raw_ac is not None and resid_ac is not None:
                    engine_results[engine_name].append(
                        (raw_ac, resid_ac, len(spends))
                    )

    print(f"Games parsed: {games_total}")
    print()

    engines = sorted(engine_results.keys(),
                     key=lambda e: (0 if "Coda" in e else 1, e))

    print("=== Move-to-move autocorrelation (lower = more position-aware) ===")
    fmt = "{:<22} {:>8} {:>14} {:>14} {:>10}"
    print(fmt.format("engine", "games", "raw acf (mean)", "resid acf (mean)", "median n"))
    print("-" * 76)
    for e in engines:
        rs = engine_results[e]
        if not rs:
            continue
        raw_avg = sum(r[0] for r in rs) / len(rs)
        resid_avg = sum(r[1] for r in rs) / len(rs)
        ns = sorted(r[2] for r in rs)
        median_n = ns[len(ns) // 2]
        print(fmt.format(
            e,
            len(rs),
            f"{raw_avg:+.3f}",
            f"{resid_avg:+.3f}",
            median_n,
        ))
    print()
    print("  Raw acf: autocorrelation of raw spends. High (0.4+) means consecutive")
    print("           moves are similar. Includes the natural clock-decay smoothness.")
    print("  Resid acf: autocorrelation after removing linear (ply) trend. This is")
    print("             the KEY metric. Low/zero/negative → position-aware variance.")
    print("             High positive → tactical clusters (multiple hard moves in a")
    print("             row). High → smooth curve.")
    print()
    print("  Reference targets:")
    print("    SF/Reckless:    resid_acf around 0.0-0.15 (mostly random residuals)")
    print("    Coda Phase 4:   expected ~0.3-0.4 (curve + small position signal)")


if __name__ == "__main__":
    main()
