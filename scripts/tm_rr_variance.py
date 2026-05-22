#!/usr/bin/env python3
"""Per-engine move-time variance analyzer for cutechess-cli round-robin PGN.

Computes for each engine across all games where it played:
  - n moves, mean, SD, coefficient of variation
  - p50 / p90 / p99 / max
  - p99 / p50 ratio (spike intensity)
  - per-game-phase mean/SD (opening, middlegame, endgame)

Designed to compare TM variance shape across engines, with SF as a
reference for "good" variance.
"""

import sys, re, math
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
            spent = parse_time_spent(comment)
            color = "white" if len(moves) % 2 == 0 else "black"
            moves.append((color, spent))
        yield headers, moves

def quantile(xs_sorted, q):
    if not xs_sorted:
        return None
    pos = q * (len(xs_sorted) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(xs_sorted) - 1)
    f = pos - lo
    return xs_sorted[lo] * (1 - f) + xs_sorted[hi] * f

def stats(xs):
    if not xs:
        return None
    xs_s = sorted(xs)
    n = len(xs_s)
    mean = sum(xs_s) / n
    var = sum((x - mean) ** 2 for x in xs_s) / max(1, n - 1)
    sd = math.sqrt(var)
    cv = sd / mean if mean > 0 else float("nan")
    p50 = quantile(xs_s, 0.50)
    p90 = quantile(xs_s, 0.90)
    p99 = quantile(xs_s, 0.99)
    ratio = (p99 / p50) if p50 > 0 else float("nan")
    return {
        "n": n, "mean": mean, "sd": sd, "cv": cv,
        "p50": p50, "p90": p90, "p99": p99, "ratio": ratio,
        "max": max(xs_s),
    }

def main():
    if len(sys.argv) < 2:
        print("usage: tm_rr_variance.py <pgn> [pgn ...]")
        sys.exit(1)

    # engine_name -> list of spends (s)
    engine_spends = defaultdict(list)
    # engine_name -> {opening:[], middle:[], end:[]}
    engine_phase = defaultdict(lambda: defaultdict(list))
    games_total = 0

    for pgn_path in sys.argv[1:]:
        with open(pgn_path) as f:
            pgn = f.read()
        for hdrs, moves in parse_games(pgn):
            white = hdrs.get("White")
            black = hdrs.get("Black")
            if not white or not black:
                continue
            games_total += 1
            for ply, (color, spent) in enumerate(moves):
                if spent is None:
                    continue
                engine = white if color == "white" else black
                engine_spends[engine].append(spent)
                full_move = ply // 2 + 1
                if full_move <= 15:
                    bucket = "opening"
                elif full_move <= 40:
                    bucket = "middle"
                else:
                    bucket = "end"
                engine_phase[engine][bucket].append(spent)

    print(f"Total games parsed: {games_total}")
    print()

    # Sort engines by Coda first, then others alphabetically
    engines = sorted(engine_spends.keys(),
                     key=lambda e: (0 if "Coda" in e else 1, e))

    print("=== Overall per-engine move-time stats ===")
    fmt = "{:<20} {:>5}  {:>7}  {:>7}  {:>5}  {:>6}  {:>6}  {:>6}  {:>6}  {:>5}"
    print(fmt.format("engine", "n", "mean", "sd", "cv", "p50", "p90", "p99", "max", "p99/p50"))
    print("-" * 95)
    for e in engines:
        s = stats(engine_spends[e])
        if s is None:
            continue
        print(fmt.format(
            e, s["n"],
            f"{s['mean']:.2f}",
            f"{s['sd']:.2f}",
            f"{s['cv']:.2f}",
            f"{s['p50']:.1f}",
            f"{s['p90']:.1f}",
            f"{s['p99']:.1f}",
            f"{s['max']:.1f}",
            f"{s['ratio']:.1f}x",
        ))
    print()

    print("=== Per-engine by game phase (mean / SD seconds) ===")
    fmt2 = "{:<20} {:>11}  {:>11}  {:>11}"
    print(fmt2.format("engine", "opening", "middle", "endgame"))
    print("-" * 60)
    for e in engines:
        cells = []
        for bucket in ("opening", "middle", "end"):
            s = stats(engine_phase[e][bucket])
            if s is None:
                cells.append("-")
            else:
                cells.append(f"{s['mean']:.1f}/{s['sd']:.1f}")
        print(fmt2.format(e, cells[0], cells[1], cells[2]))
    print()

    # SF comparison: ratios relative to SF
    if any("Stockfish" in e for e in engines):
        sf_name = next(e for e in engines if "Stockfish" in e)
        sf_s = stats(engine_spends[sf_name])
        print(f"=== Variance comparison to {sf_name} (ratio: engine/SF) ===")
        fmt3 = "{:<20} {:>8} {:>8} {:>10}"
        print(fmt3.format("engine", "SD/SF.SD", "CV/SF.CV", "ratio/SF.ratio"))
        print("-" * 50)
        for e in engines:
            if e == sf_name:
                continue
            s = stats(engine_spends[e])
            if s is None:
                continue
            print(fmt3.format(
                e,
                f"{s['sd']/sf_s['sd']:.2f}x",
                f"{s['cv']/sf_s['cv']:.2f}x",
                f"{s['ratio']/sf_s['ratio']:.2f}x",
            ))
        print()
        print(f"  Reading: 1.0× = matches SF. <1.0 = less variance than SF (smoother).")
        print(f"           SF: SD={sf_s['sd']:.2f}s, CV={sf_s['cv']:.2f}, p99/p50={sf_s['ratio']:.1f}x")

if __name__ == "__main__":
    main()
