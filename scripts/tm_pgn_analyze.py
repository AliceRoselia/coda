#!/usr/bin/env python3
"""
Analyze cutechess-cli PGN output for TM Phase 1 validation.

Outputs:
- W/L/D + nELO ± 95% CI vs main
- Time-forfeit count per engine
- Per-move time distribution: mean/SD/p10/p50/p90/p99 per engine
- Optional: histogram of per-move times in 10 bins
"""

import sys
import re
import math
import argparse
from collections import defaultdict


def parse_time_spent(comment):
    """cutechess-cli PGN comment format: '{eval/depth time_used_s}'.

    Examples:
      {0.00/19 1.9s}                            → 1.9
      {+0.09/19 2.0s}                           → 2.0
      {0.00/19 0.91s, Draw by 3-fold repetition} → 0.91
      {0.00/22 1.1ms}                           → 0.0011
      {book}                                    → None
      {-M5/24 0.043s}                           → 0.043

    Returns time spent in seconds, or None if not present.
    """
    # Match a token like "1.9s" or "0.91s" or "1.1ms" at end of token
    m = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*(s|ms)\b", comment)
    if not m:
        return None
    value = float(m.group(1))
    unit = m.group(2)
    if unit == "ms":
        return value / 1000.0
    return value


def parse_games(pgn_text):
    """Yield (headers_dict, moves_list).

    moves_list: list of (color, clk_seconds_after_move_or_None).
    """
    # Split by blank line followed by [Event — robust for cutechess PGN.
    games = re.split(r"\n\n(?=\[Event)", pgn_text)
    for g in games:
        if not g.strip():
            continue
        headers = {}
        # Header lines
        for line in g.split("\n"):
            m = re.match(r'\[(\w+)\s+"(.*)"\]', line.strip())
            if m:
                headers[m.group(1)] = m.group(2)
        # Movetext: everything after the blank line
        parts = g.split("\n\n", 1)
        movetext = parts[1] if len(parts) > 1 else ""

        # Parse SAN tokens + their {comment} content.
        # We don't need SAN parsing — just iterate (move_index, comment).
        tokens = re.finditer(
            r"(?:(\d+)\.(?:\.\.)?)?\s*(\S+?)\s*\{([^}]*)\}", movetext
        )
        moves = []
        for tok in tokens:
            move_num_str, san, comment = tok.group(1), tok.group(2), tok.group(3)
            if san in ("1-0", "0-1", "1/2-1/2", "*"):
                continue
            spent = parse_time_spent(comment)
            # Color: odd half-move = white, even = black.
            color = "white" if len(moves) % 2 == 0 else "black"
            moves.append((color, spent))
        yield headers, moves


def per_move_times(moves, increment_s):
    """Each move comment already has its own per-move time spent.
    Returns (white_spends, black_spends).
    `increment_s` retained for API compat but unused here.
    """
    _ = increment_s
    spends_white = []
    spends_black = []
    for (color, spent) in moves:
        if spent is None:
            continue
        if color == "white":
            spends_white.append(spent)
        else:
            spends_black.append(spent)
    return spends_white, spends_black


def quantile(sorted_xs, q):
    if not sorted_xs:
        return None
    pos = q * (len(sorted_xs) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(sorted_xs) - 1)
    frac = pos - lo
    return sorted_xs[lo] * (1 - frac) + sorted_xs[hi] * frac


def elo_from_wld(wins, losses, draws):
    n = wins + losses + draws
    if n == 0:
        return None, None
    score = (wins + 0.5 * draws) / n
    score = min(0.9999, max(0.0001, score))
    elo = -400.0 * math.log10(1.0 / score - 1.0)
    # Wald 95% CI on score, then convert
    p = score
    se = math.sqrt(p * (1 - p) / n)
    p_lo = max(0.0001, p - 1.96 * se)
    p_hi = min(0.9999, p + 1.96 * se)
    elo_lo = -400.0 * math.log10(1.0 / p_lo - 1.0)
    elo_hi = -400.0 * math.log10(1.0 / p_hi - 1.0)
    return elo, (elo_hi - elo_lo) / 2.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pgn", help="cutechess-cli PGN output file")
    ap.add_argument(
        "--engine-a",
        default="Coda.phase1",
        help="Name of branch engine in PGN (tournament under test)",
    )
    ap.add_argument(
        "--engine-b", default="Coda.main", help="Name of baseline engine"
    )
    ap.add_argument(
        "--increment", type=float, default=0.5, help="Increment seconds (per move)"
    )
    args = ap.parse_args()

    with open(args.pgn) as f:
        pgn = f.read()

    a_wins = a_losses = a_draws = 0
    a_time_forfeits = 0
    b_time_forfeits = 0
    a_times = []
    b_times = []
    games_total = 0
    crashes = 0

    for headers, moves in parse_games(pgn):
        white = headers.get("White", "")
        black = headers.get("Black", "")
        result = headers.get("Result", "*")
        termination = headers.get("Termination", "").lower()
        if not white or not black:
            continue
        games_total += 1

        # Identify A vs B sides.
        a_is_white = white == args.engine_a
        a_is_black = black == args.engine_a
        if not (a_is_white or a_is_black):
            continue  # Game doesn't involve A (shouldn't happen in gauntlet)

        # Result for A
        if result == "1-0":
            if a_is_white: a_wins += 1
            else: a_losses += 1
        elif result == "0-1":
            if a_is_black: a_wins += 1
            else: a_losses += 1
        elif result == "1/2-1/2":
            a_draws += 1
        elif "crash" in termination or "stalled" in termination or "illegal" in termination:
            crashes += 1

        # Termination: time forfeit?
        # cutechess uses "time forfeit" or "lost on time" in Termination.
        if "time" in termination and ("forfeit" in termination or "loss" in termination or "out" in termination):
            # Whose time?
            # cutechess: "1-0 {Black loses on time}" → loser is the side not matching the winner
            # The result field tells us the loser; map to engine.
            if result == "1-0":
                # Black lost
                if a_is_black: a_time_forfeits += 1
                else: b_time_forfeits += 1
            elif result == "0-1":
                # White lost
                if a_is_white: a_time_forfeits += 1
                else: b_time_forfeits += 1

        # Per-move times
        white_spends, black_spends = per_move_times(moves, args.increment)
        a_spends = white_spends if a_is_white else black_spends
        b_spends = black_spends if a_is_white else white_spends
        a_times.extend(a_spends)
        b_times.extend(b_spends)

    print(f"PGN: {args.pgn}")
    print(f"Games parsed: {games_total}")
    print(f"Crashes: {crashes}")
    print()

    print(f"=== Results: {args.engine_a} vs {args.engine_b} ===")
    n = a_wins + a_losses + a_draws
    print(f"  W/L/D: {a_wins} / {a_losses} / {a_draws}  (n={n})")
    if n:
        score = (a_wins + 0.5 * a_draws) / n
        elo, ci = elo_from_wld(a_wins, a_losses, a_draws)
        print(f"  Score: {score:.3f}   Elo: {elo:+.1f} ± {ci:.1f}")
    print()

    print(f"=== Time forfeits ===")
    print(f"  {args.engine_a}: {a_time_forfeits}")
    print(f"  {args.engine_b}: {b_time_forfeits}")
    print()

    def stats_line(name, xs):
        if not xs:
            print(f"  {name}: (no data)")
            return
        xs_s = sorted(xs)
        n = len(xs_s)
        mean = sum(xs_s) / n
        var = sum((x - mean) ** 2 for x in xs_s) / max(1, n - 1)
        sd = math.sqrt(var)
        print(
            f"  {name}:  n={n:>5}  mean={mean*1000:>6.0f}ms  sd={sd*1000:>6.0f}ms  "
            f"p10={quantile(xs_s, 0.10)*1000:>6.0f}  "
            f"p50={quantile(xs_s, 0.50)*1000:>6.0f}  "
            f"p90={quantile(xs_s, 0.90)*1000:>6.0f}  "
            f"p99={quantile(xs_s, 0.99)*1000:>6.0f}  "
            f"max={max(xs_s)*1000:>6.0f}"
        )

    print(f"=== Per-move time spend (ms) ===")
    stats_line(args.engine_a, a_times)
    stats_line(args.engine_b, b_times)
    print()

    # Time by game phase (uses ply count from each game)
    print(f"=== Time spend by game phase (ms) ===")
    a_open, a_mid, a_end = [], [], []
    b_open, b_mid, b_end = [], [], []
    for headers, moves in parse_games(pgn):
        white = headers.get("White", "")
        black = headers.get("Black", "")
        if white != args.engine_a and black != args.engine_a:
            continue
        a_is_white = white == args.engine_a
        for ply, (color, spent) in enumerate(moves):
            if spent is None:
                continue
            is_a = (color == "white") == a_is_white
            bucket_o = a_open if is_a else b_open
            bucket_m = a_mid if is_a else b_mid
            bucket_e = a_end if is_a else b_end
            full_move = ply // 2 + 1
            if full_move <= 15:
                bucket_o.append(spent)
            elif full_move <= 40:
                bucket_m.append(spent)
            else:
                bucket_e.append(spent)

    def phase_line(label, name, xs):
        if not xs:
            print(f"  {label:10} {name}: (no data)")
            return
        xs_s = sorted(xs)
        n = len(xs_s)
        mean = sum(xs_s) / n
        var = sum((x - mean) ** 2 for x in xs_s) / max(1, n - 1)
        sd = math.sqrt(var)
        print(
            f"  {label:10} {name:15}: n={n:>5}  mean={mean*1000:>6.0f}ms  sd={sd*1000:>6.0f}ms  "
            f"p50={quantile(xs_s, 0.50)*1000:>6.0f}  p90={quantile(xs_s, 0.90)*1000:>6.0f}  p99={quantile(xs_s, 0.99)*1000:>6.0f}"
        )

    phase_line("opening", args.engine_a, a_open)
    phase_line("opening", args.engine_b, b_open)
    phase_line("middlegame", args.engine_a, a_mid)
    phase_line("middlegame", args.engine_b, b_mid)
    phase_line("endgame", args.engine_a, a_end)
    phase_line("endgame", args.engine_b, b_end)
    print()

    # Histogram (10 log-spaced bins from p1 to p99)
    if a_times and b_times:
        all_times = sorted(a_times + b_times)
        lo = max(quantile(all_times, 0.01), 0.001)
        hi = quantile(all_times, 0.99)
        if hi > lo:
            n_bins = 10
            edges = [
                lo * (hi / lo) ** (i / n_bins) for i in range(n_bins + 1)
            ]
            print(f"=== Histogram (log bins {lo*1000:.0f}..{hi*1000:.0f}ms) ===")
            print(f"  {'range (ms)':>20}  {args.engine_a:>15}  {args.engine_b:>15}")
            for i in range(n_bins):
                lo_e, hi_e = edges[i], edges[i + 1]
                a_n = sum(1 for x in a_times if lo_e <= x < hi_e)
                b_n = sum(1 for x in b_times if lo_e <= x < hi_e)
                rng = f"{lo_e*1000:>7.0f}..{hi_e*1000:.0f}"
                pct_a = 100 * a_n / max(1, len(a_times))
                pct_b = 100 * b_n / max(1, len(b_times))
                print(
                    f"  {rng:>20}  {a_n:>5} ({pct_a:>5.1f}%) "
                    f"{b_n:>5} ({pct_b:>5.1f}%)"
                )


if __name__ == "__main__":
    main()
