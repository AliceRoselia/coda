#!/usr/bin/env python3
"""Move-time distribution analyzer — focuses on the lichess-graph view.

Three layers of analysis:

1. Bimodality metrics — quantify the "lots of near-zero PLUS lots of long thinks"
   shape that SF and other top engines exhibit. Low autocorrelation alone
   isn't enough: a perfectly uniform alternating pattern (0.5s, 3s, 0.5s, 3s)
   has low autocorrelation but is NOT what we want. We want spikes that
   correlate with position difficulty.

   - low_pct: fraction of moves <= 0.3 × p50 (the "emit instantly" tail)
   - high_pct: fraction of moves >= 2 × p50 (the "spike up on hard" tail)
   - bimodality = low_pct + high_pct (loose measure — higher is more bimodal)
   - max/p50 ratio: peak spread vs typical

2. ASCII move-time chart — lichess-style per-game visualization of both
   engines' move times side-by-side. Each tick = 0.5s. Helps see whether
   spikes line up between players (tactical moments) or look random.

3. Spike correlation — do the engine's longer thinks coincide with the
   OPPONENT's longer thinks? If yes, both players are spiking on the
   same hard positions (good signal: spend is position-aware).

Usage:
  python3 scripts/tm_move_distribution.py <pgn>
  python3 scripts/tm_move_distribution.py <pgn> --chart --max-charts 3
"""

import sys, re, math, argparse
from collections import defaultdict


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
        # Match move + comment block. Comment format: {eval/depth time_s} or just {time_s}
        # We want the LAST numeric value in the comment (the time).
        moves = []
        for tok in re.finditer(r"(?:(\d+)\.(?:\.\.)?)?\s*(\S+?)\s*\{([^}]*)\}", movetext):
            san, comment = tok.group(2), tok.group(3)
            if san in ("1-0", "0-1", "1/2-1/2", "*"):
                continue
            # Time is typically the LAST numeric token followed by 's' or 'ms'
            m = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*(ms|s)\b\s*\}?$", comment)
            if not m:
                m = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*(ms|s)\b", comment)
            if not m:
                continue
            v = float(m.group(1))
            t = v / 1000.0 if m.group(2) == "ms" else v
            color = "white" if len(moves) % 2 == 0 else "black"
            moves.append((color, san, t))
        yield headers, moves


def stats(xs):
    if not xs:
        return None
    xs_s = sorted(xs)
    n = len(xs_s)
    def q(p): return xs_s[min(int(p * n), n - 1)]
    p10 = q(0.10); p50 = q(0.50); p90 = q(0.90)
    return {
        "n": n,
        "p10": p10, "p25": q(0.25), "p50": p50,
        "p75": q(0.75), "p90": p90, "p99": q(0.99),
        "max": xs_s[-1],
        "low_pct": 100 * sum(1 for x in xs if x <= 0.3 * p50) / n,
        "high_pct": 100 * sum(1 for x in xs if x >= 2.0 * p50) / n,
        "p90_p10": p90 / p10 if p10 > 0 else float("nan"),
        "p90_p50": p90 / p50 if p50 > 0 else float("nan"),
        "max_p50": xs_s[-1] / p50 if p50 > 0 else float("nan"),
    }


def ascii_chart(moves, width=80):
    """Lichess-style two-row chart: white above zero, black below.

    Each bar is the move time scaled relative to the game's max.
    """
    if not moves:
        return "(empty)"
    times_w = [t for c, _, t in moves if c == "white" and t is not None]
    times_b = [t for c, _, t in moves if c == "black" and t is not None]
    all_t = [t for _, _, t in moves if t is not None]
    if not all_t:
        return "(no times)"
    tmax = max(all_t)
    h = 8  # height of one half
    lines = []
    # White bars (top, growing up)
    for row in range(h, 0, -1):
        line = ""
        for c, _, t in moves:
            if c != "white": continue
            if t is None: line += " "
            elif t / tmax * h >= row: line += "#"
            else: line += " "
        lines.append(line)
    lines.append("-" * len([m for m in moves if m[0] == "white"]))
    # Black bars (bottom, growing down)
    for row in range(1, h + 1):
        line = ""
        for c, _, t in moves:
            if c != "black": continue
            if t is None: line += " "
            elif t / tmax * h >= row: line += "#"
            else: line += " "
        lines.append(line)
    return "\n".join(lines)


def spike_correlation(moves_w, moves_b):
    """Are white's long thinks aligned with black's long thinks?

    Returns Pearson correlation of move times, paired by ply.
    Positive => both spike at same positions (good — position-aware).
    Near zero => spikes uncorrelated.
    """
    n = min(len(moves_w), len(moves_b))
    if n < 3:
        return None
    w = moves_w[:n]
    b = moves_b[:n]
    mw = sum(w) / n
    mb = sum(b) / n
    cov = sum((w[i] - mw) * (b[i] - mb) for i in range(n))
    vw = sum((x - mw) ** 2 for x in w)
    vb = sum((x - mb) ** 2 for x in b)
    if vw <= 0 or vb <= 0:
        return None
    return cov / math.sqrt(vw * vb)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pgn")
    ap.add_argument("--chart", action="store_true", help="Print ASCII move-time charts")
    ap.add_argument("--max-charts", type=int, default=2, help="How many sample games to chart")
    args = ap.parse_args()

    with open(args.pgn) as f:
        pgn = f.read()

    # engine -> list of all move times
    engine_times = defaultdict(list)
    # (engine, opponent) -> list of game-pair move sequences
    pair_games = defaultdict(list)
    games_total = 0

    chart_samples = []

    for hdrs, moves in parse_games(pgn):
        w_name = hdrs.get("White")
        b_name = hdrs.get("Black")
        if not w_name or not b_name:
            continue
        games_total += 1
        w_times = [t for c, _, t in moves if c == "white" and t is not None]
        b_times = [t for c, _, t in moves if c == "black" and t is not None]
        engine_times[w_name].extend(w_times)
        engine_times[b_name].extend(b_times)
        pair_games[(w_name, b_name)].append((w_times, b_times, moves))
        if len(chart_samples) < args.max_charts and len(moves) > 20:
            chart_samples.append((hdrs, moves))

    print(f"Games parsed: {games_total}\n")

    engines = sorted(engine_times.keys())

    print("=== Distribution shape per engine ===")
    fmt = "{:<22} {:>6} {:>7} {:>7} {:>7} {:>7} {:>7} {:>8} {:>8} {:>7} {:>7}"
    print(fmt.format("engine", "n", "p10", "p25", "p50", "p75", "p90", "p90/p10", "p90/p50", "<0.3p50", ">=2p50"))
    print("-" * 110)
    for e in engines:
        s = stats(engine_times[e])
        if not s:
            continue
        print(fmt.format(
            e, s["n"],
            f"{s['p10']:.2f}", f"{s['p25']:.2f}", f"{s['p50']:.2f}",
            f"{s['p75']:.2f}", f"{s['p90']:.2f}",
            f"{s['p90_p10']:.1f}x", f"{s['p90_p50']:.1f}x",
            f"{s['low_pct']:.1f}%", f"{s['high_pct']:.1f}%",
        ))
    print()
    print("  <0.3p50: % of moves emitted at ≤30% of median (the 'emit fast' tail —")
    print("           mostly ponderhit cases). SF target: 20-30%.")
    print("  >=2p50:  % of moves at ≥2× median (the 'spike on hard' tail).")
    print("           SF target: 10-15%.")
    print("  Bimodal engines have BOTH high. Uniform engines have neither.")
    print()

    if args.chart:
        print("=== Sample game charts ===")
        for hdrs, moves in chart_samples:
            print(f"\n[White] {hdrs.get('White')}  vs  [Black] {hdrs.get('Black')}")
            print(f"  Result: {hdrs.get('Result', '?')}  TimeControl: {hdrs.get('TimeControl', '?')}")
            print(ascii_chart(moves))
        print()

    # Spike correlation: are players' longer thinks correlated within a game?
    print("=== Spike correlation per pairing ===")
    print("  (Pearson of white_time vs black_time, paired by ply. Higher = both")
    print("   players spike at same positions = position-aware.)")
    print()
    fmt2 = "{:<22} vs {:<22}  {:>6} games  {:>8}"
    print(fmt2.format("white", "black", "n", "spike-r"))
    print("-" * 75)
    for (w, b), games in sorted(pair_games.items()):
        if len(games) < 1:
            continue
        rs = []
        for wt, bt, _ in games:
            r = spike_correlation(wt, bt)
            if r is not None:
                rs.append(r)
        if rs:
            mean_r = sum(rs) / len(rs)
            print(fmt2.format(w, b, len(rs), f"{mean_r:+.3f}"))


if __name__ == "__main__":
    main()
