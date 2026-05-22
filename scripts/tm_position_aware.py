#!/usr/bin/env python3
"""Position-aware TM analyzer for cutechess-cli PGN.

Extends `tm_rr_variance.py` to classify each move as TACTICAL or ROUTINE
based on the eval/depth signals in cutechess comments, then reports:

  - Tactical/routine spend ratio per engine (target: ≥ 3.0 for SF-like)
  - Burst events per game (moves with spend > 3× engine median)
  - Clock-curve smoothness: residual variance after fitting spend ~ time_remaining
    (low residual = pure curve behavior; high residual = position-aware)

Cutechess comments are `{eval/depth time_s}` — we parse all three.
Eval is from the engine's perspective in centipawns (or M±N for mate).

Tactical classification heuristic:
  - |eval_delta vs same engine's prev move| > 50cp  → tactical
  - mate score appeared/disappeared → tactical
  - depth < (engine_median_depth - 2) → tactical (search cut short)
  - else → routine

Usage:
  python3 scripts/tm_position_aware.py <pgn> [pgn ...]
"""

import sys, re, math, argparse
from collections import defaultdict

def parse_comment(comment):
    """cutechess `{[+-]eval/depth time_s}` → (eval_cp, depth, time_s).

    Eval may be float centipawns ("+0.34"), mate ("-M3"), or absent for
    book moves. Depth is integer. Time has 's' or 'ms' suffix.

    Returns (eval_cp_or_None, depth_or_None, time_s_or_None).
    Eval mate is encoded as ±9000 + ply distance to keep it numeric.
    """
    eval_cp = None
    depth = None
    time_s = None

    # eval: signed number optionally with M for mate, then /
    m = re.search(r"([+-]?(?:M|m)?\s*[0-9]+(?:\.[0-9]+)?)\s*/", comment)
    if m:
        s = m.group(1).strip()
        if 'M' in s.upper():
            sign = -1 if s.startswith('-') else 1
            n = int(re.search(r"\d+", s).group(0))
            eval_cp = sign * (9000 + n)
        else:
            try:
                eval_cp = float(s) * 100  # pawns → cp
            except ValueError:
                pass

    # depth: /N
    m = re.search(r"/(\d+)", comment)
    if m:
        depth = int(m.group(1))

    # time
    m = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*(s|ms)\b", comment)
    if m:
        v = float(m.group(1))
        time_s = v / 1000.0 if m.group(2) == "ms" else v

    return eval_cp, depth, time_s


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
            ev, dep, t = parse_comment(comment)
            color = "white" if len(moves) % 2 == 0 else "black"
            moves.append((color, san, ev, dep, t))
        yield headers, moves


def quantile(xs_sorted, q):
    if not xs_sorted:
        return None
    pos = q * (len(xs_sorted) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(xs_sorted) - 1)
    f = pos - lo
    return xs_sorted[lo] * (1 - f) + xs_sorted[hi] * f


def classify_moves(moves_engine):
    """Given list of (san, eval_cp, depth, time_s, ply) for one engine in
    one game, classify each move as 'tactical' or 'routine'.

    Tactical (SAN-based proxy for "position has forcing/scary content"):
      - Capture (`x` in SAN)
      - Check (`+`)
      - Mate (`#`)
      - Promotion (`=`)

    SAN proxy beats eval-delta because eval-delta catches forced captures
    (engine emits fast on x) which dominate the "tactical" bucket and
    invert the ratio. SAN catches the actual class of position the
    engine just played FROM.

    Returns list of (classification, time_s).
    """
    out = []
    for san, ev, dep, t, ply in moves_engine:
        if t is None:
            continue
        is_tactical = ('x' in san) or ('+' in san) or ('#' in san) or ('=' in san)
        out.append(("tactical" if is_tactical else "routine", t))
    return out


def stats(xs):
    if not xs:
        return None
    xs_s = sorted(xs)
    n = len(xs_s)
    mean = sum(xs_s) / n
    var = sum((x - mean) ** 2 for x in xs_s) / max(1, n - 1)
    sd = math.sqrt(var)
    return {
        "n": n, "mean": mean, "sd": sd,
        "p50": quantile(xs_s, 0.50),
        "p90": quantile(xs_s, 0.90),
        "p99": quantile(xs_s, 0.99),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pgns", nargs="+")
    args = ap.parse_args()

    # engine -> list of (classification, time_s)
    engine_classified = defaultdict(list)
    # engine -> list of (game_id, list_of_spends) — for burst detection
    engine_games = defaultdict(list)
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
            # Split moves per engine, attaching ply
            w_moves = [(san, ev, dep, t, i) for i, (c, san, ev, dep, t) in enumerate(moves) if c == "white"]
            b_moves = [(san, ev, dep, t, i) for i, (c, san, ev, dep, t) in enumerate(moves) if c == "black"]

            for engine, em in [(white, w_moves), (black, b_moves)]:
                classified = classify_moves(em)
                engine_classified[engine].extend(classified)
                spends = [t for _, t in classified]
                engine_games[engine].append((games_total, spends))

    print(f"Games parsed: {games_total}")
    print()

    engines = sorted(engine_classified.keys(),
                     key=lambda e: (0 if "Coda" in e else 1, e))

    # Spend distribution shape: peak/median ratio + decile stats
    print("=== Spend distribution shape (key bimodality metric) ===")
    fmt = "{:<22} {:>8} {:>8} {:>8} {:>8} {:>10}"
    print(fmt.format("engine", "p50", "p90", "p99", "max", "max/p50"))
    print("-" * 70)
    for e in engines:
        all_spends = [t for _, t in engine_classified[e]]
        s = stats(all_spends)
        if s:
            ratio = s["p99"] / s["p50"] if s["p50"] > 0 else float("nan")
            ms = max(all_spends)
            mr = ms / s["p50"] if s["p50"] > 0 else float("nan")
            print(fmt.format(
                e,
                f"{s['p50']:.2f}",
                f"{s['p90']:.2f}",
                f"{s['p99']:.2f}",
                f"{ms:.2f}",
                f"{mr:.1f}x",
            ))
    print()
    print("  max/p50: peak spend relative to typical. Bimodal engines (SF) ≈ 10-15x.")
    print("  Smooth-curve engines (Phase 2) ≈ 5-7x.")
    print()

    # Burst events: spend > 3× engine median
    print("=== Burst events per game (spend > 3× engine median) ===")
    fmt2 = "{:<22} {:>10}  {:>10}  {:>10}"
    print(fmt2.format("engine", "bursts/g", "games", "median"))
    print("-" * 60)
    for e in engines:
        all_spends = [t for _, t in engine_classified[e]]
        if not all_spends:
            continue
        med = sorted(all_spends)[len(all_spends) // 2]
        threshold = 3 * med
        total_bursts = 0
        total_games = 0
        for game_id, spends in engine_games[e]:
            if not spends:
                continue
            total_games += 1
            total_bursts += sum(1 for s in spends if s > threshold)
        bursts_per_game = total_bursts / max(1, total_games)
        print(fmt2.format(e, f"{bursts_per_game:.2f}", f"{total_games}", f"{med:.2f}s"))
    print()
    print("  Target 2-5 bursts/game (SF-like). Phase 4 v2.1 Coda: ~0-1 expected.")
    print()

    # Clock-curve smoothness: residual of linear fit (spend vs time_remaining)
    # For each engine: reconstruct clock trajectory and fit spend = a*time_remaining + b.
    # Residual SD = how much position-aware variance exists on top of the curve.
    print("=== Clock-curve smoothness (residual variance) ===")
    fmt3 = "{:<22} {:>10} {:>14} {:>14} {:>10}"
    print(fmt3.format("engine", "n moves", "curve SD", "residual SD", "% residual"))
    print("-" * 76)
    for e in engines:
        # For each game, walk the moves and compute time_remaining BEFORE each move
        # then pair with the spend. Skip games where we lack clock info.
        # Note: we don't have TC info easily here; just track cumulative spend.
        # Instead use ply index as proxy for "time pressure" — same idea.
        pairs = []  # (ply_index_in_game, spend)
        for game_id, spends in engine_games[e]:
            for i, s in enumerate(spends):
                pairs.append((i, s))
        if len(pairs) < 10:
            continue
        # Linear fit spend = a*ply + b (ply represents game progression / clock decay)
        n = len(pairs)
        sx = sum(p[0] for p in pairs)
        sy = sum(p[1] for p in pairs)
        sxx = sum(p[0]*p[0] for p in pairs)
        sxy = sum(p[0]*p[1] for p in pairs)
        denom = n * sxx - sx * sx
        if denom == 0:
            continue
        a = (n * sxy - sx * sy) / denom
        b = (sy - a * sx) / n
        # Residuals
        residuals = [p[1] - (a * p[0] + b) for p in pairs]
        mean_r = sum(residuals) / n
        var_r = sum((r - mean_r) ** 2 for r in residuals) / max(1, n - 1)
        sd_r = math.sqrt(var_r)
        # Total SD
        mean_y = sy / n
        var_y = sum((p[1] - mean_y) ** 2 for p in pairs) / max(1, n - 1)
        sd_y = math.sqrt(var_y)
        pct_residual = 100 * sd_r / sd_y if sd_y > 0 else 0
        print(fmt3.format(e, n, f"{sd_y:.2f}", f"{sd_r:.2f}", f"{pct_residual:.1f}%"))
    print()
    print("  Curve SD = total variance of spends. Residual SD = variance after removing")
    print("  linear trend (= 'spend ~ clock_remaining' explanation). Higher % residual =")
    print("  more position-driven variance (good); lower = more curve-bound (Coda today).")


if __name__ == "__main__":
    main()
