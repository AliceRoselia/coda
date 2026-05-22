#!/usr/bin/env python3
"""Analyze per-move time spend from a lichess PGN with [%clk h:mm:ss]."""

import sys, re, math, os

def parse_clk(s):
    # "h:mm:ss" or "mm:ss" or "h:mm:ss.f"
    parts = s.split(":")
    if len(parts) == 3:
        h, m, sec = parts
    elif len(parts) == 2:
        h = "0"
        m, sec = parts
    else:
        return None
    return int(h) * 3600 + int(m) * 60 + float(sec)

def main():
    for pgn_path in sys.argv[1:]:
        with open(pgn_path) as f:
            text = f.read()
        # headers
        white = re.search(r'\[White "([^"]+)"\]', text).group(1)
        black = re.search(r'\[Black "([^"]+)"\]', text).group(1)
        tc = re.search(r'\[TimeControl "([^"]+)"\]', text).group(1)
        # Parse base+inc
        base_s, inc_s = tc.split("+")
        base, inc = int(base_s), int(inc_s)
        # Find all clock annotations in move order
        clocks = []
        for m in re.finditer(r'\{\s*\[%clk\s+([0-9:.]+)\]\s*\}', text):
            t = parse_clk(m.group(1))
            if t is not None:
                clocks.append(t)
        # half-move i: even=white, odd=black
        # spent_i = clock_{i-2} - clock_i + inc, with clock_{-2} = base, clock_{-1} = base
        spends_white, spends_black = [], []
        for i, clk in enumerate(clocks):
            prev = clocks[i-2] if i >= 2 else float(base)
            spent = prev - clk + inc
            if spent < 0:
                continue  # broken/disconnect/adjudication
            if i % 2 == 0:
                spends_white.append(spent)
            else:
                spends_black.append(spent)
        coda_is_white = "coda" in white.lower()
        coda_spends = spends_white if coda_is_white else spends_black
        opp_spends = spends_black if coda_is_white else spends_white
        coda_name = white if coda_is_white else black
        opp_name = black if coda_is_white else white
        print(f"=== {os.path.basename(pgn_path)}  TC={tc}  base={base}s inc={inc}s ===")
        print(f"  {coda_name} (Coda, {'W' if coda_is_white else 'B'}) vs {opp_name}")
        if not coda_spends:
            print("  no moves"); print(); continue
        xs = sorted(coda_spends)
        n = len(xs)
        mean = sum(xs)/n
        var = sum((x-mean)**2 for x in xs) / max(1, n-1)
        sd = math.sqrt(var)
        def q(p):
            pos = p * (n - 1)
            lo, hi = int(pos), min(int(pos)+1, n-1)
            return xs[lo] * (1 - (pos - lo)) + xs[hi] * (pos - lo)
        print(f"  Coda moves: n={n}  mean={mean:.2f}s  sd={sd:.2f}s  "
              f"p10={q(0.1):.2f}  p50={q(0.5):.2f}  p90={q(0.9):.2f}  "
              f"p99={q(0.99):.2f}  max={max(xs):.2f}")
        # In-order spend sequence (moves 1-30 for the eye)
        seq = ", ".join(f"{s:.1f}" for s in coda_spends[:30])
        print(f"  Coda first 30 spends: {seq}")
        # Histogram
        bins = [0.5, 1, 2, 3, 5, 8, 12, 18, 30, 60]
        hist = [0] * (len(bins) + 1)
        for s in coda_spends:
            placed = False
            for j, b in enumerate(bins):
                if s < b:
                    hist[j] += 1
                    placed = True
                    break
            if not placed:
                hist[-1] += 1
        print("  histogram:")
        prev = 0
        for j, b in enumerate(bins):
            print(f"    [{prev:>5.1f},{b:>5.1f}) : {hist[j]:>3} ({100*hist[j]/n:>5.1f}%)")
            prev = b
        print(f"    [{prev:>5.1f},  inf) : {hist[-1]:>3} ({100*hist[-1]/n:>5.1f}%)")
        print()

if __name__ == "__main__":
    main()
