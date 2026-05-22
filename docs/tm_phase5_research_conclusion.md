# TM Phase 5 — Research Conclusion (Final)

**Date:** 2026-05-22
**TL;DR:** Phase 5 multiplier-knob attempts are exhausted. Coda Phase 4 v2.1
has measurably higher residual autocorrelation than SF/Reckless in
no-ponder mode (~0.09 vs ~0.03), but every attempt to close the gap via
multiplier-floor adjustments regresses Elo by ~40-50 per ~0.03
autocorrelation reduction. The trade is unfavorable. Coda's TM is at
the practical limit of position-aware variance within the current
architecture.

## Initial hypothesis (going in)

Lichess move-time graphs showed Coda's spend pattern as a smooth decay
curve, while SF/Reckless showed apparent bimodal "burst on tactical,
near-zero on routine" behavior. Initial measurement using max/p50 ratio
and other distribution metrics suggested Coda was at ~6-8× while
SF/Reckless were at ~22×.

Plan: widen Coda's caps, raise bmc multipliers, lower stability floors —
let multipliers express position-aware variance.

## What we tried

| Phase | Change | Result |
|---|---|---|
| 5a | Wider mid/endgame hard cap (12-28%) | Null (max/p50 7.3 vs 7.9) |
| 5b | bmc cap 2.5 → 6.0 | Null (5.0 vs 5.0) |
| 5c | 5a + 5b combined, hard cap 50-75% | Null (6.1 vs 5.6) |
| 5d | 5c + SF-style bmc coefficient | Marginal (9.2 vs 8.3) |
| 5e | nodes_factor floor 0.20, stability table to 0.30 | Autocorr ↓ slightly, **Elo −42 at 111g** |
| 5f | nodes_factor floor 0.45, stability table to 0.55 | Autocorr ↓ 0.03, **Elo −49 at 56g** |

## Metric correction along the way

Distribution metrics (max/p50, p99) turned out to be misleading — they're
inflated by:
1. **Natural clock decay** (spend follows soft(t), so distribution
   spreads even without position signal).
2. **Optimistic ponderhit** in SF (near-zero spends drag p50 down,
   inflating max/p50 ratio).

The user identified the right metric: **lag-1 residual autocorrelation**.
Compute spend correlation between adjacent moves AFTER detrending out
the linear clock-decay component. SF/Reckless show near-zero residual
autocorrelation (each move's spend independent of previous);
Coda has consistent ~0.06-0.09 in no-ponder, ~0.43 in ponder-on.

## Final reference data (120-game no-ponder RR at 120+1)

| Engine | Residual autocorrelation | Elo (in this RR) |
|---|---|---|
| Stockfish | 0.031 | +147 |
| Reckless | 0.022 | +39 |
| **Coda.main (Phase 4 v2.1)** | **0.091** | −197 |

Coda gap to top engines: **~0.06**. Real, persistent across all sample
sizes tested (8g, 30g, 65g, 95g, 120g).

## Why all Phase 5 attempts failed

The "knobs" tried (nodes_factor floor, stability table convergence,
hard cap width, bmc coefficient) all assume the engine SHOULD spend
less on positions where multipliers indicate confidence.

The problem: **Coda's confidence signals (stability_factor builds up,
nodes_factor at high frac) correlate with positions where the engine
would still benefit from more time.** Stable positions in Coda's
search are not necessarily positions where the actual best move is
obvious to the opponent. Emitting fast on these costs Elo even though
it reduces autocorrelation.

SF/Reckless probably have:
- Stronger eval signals that more reliably indicate "this is settled"
- Different search dynamics that produce more genuinely-random bmc
  fires (decorrelating consecutive moves)
- More aggressive forced-move detection (Viridithas has explicit
  one-legal / strong-forced / weak-forced classification)

These are architectural differences, not parameter tweaks.

## Conclusion

**Phase 5 is exhausted as a multiplier-knob direction.** The autocorrelation
gap to SF/Reckless is structural, requiring either:

1. **A different position-complexity signal** (not derivable from
   bmc/nodes/stability — needs explicit position analysis)
2. **An architectural refactor** that decouples multipliers from search
   dynamics (e.g., Viridithas-style forced-move detector with
   per-class fixed multipliers)
3. **Better eval/search that makes "stable" detection more reliable**

All are large research projects, not parameter tweaks.

**Coda's current TM is acceptable for production**:
- No-ponder autocorrelation 0.09 (vs SF 0.03) — small gap, real but minor
- Phase 4 v2.1 banked +3.3 Elo SPRT-validated
- Phase 2 banked +4.5 Elo SPRT-validated

## Pivoting to Thread B

The bigger remaining problem is ponder-on autocorrelation (Coda 0.43 vs
SF 0.01) — a 14× gap from verify-always-on-ponderhit forcing every move
to have non-trivial spend. This is the lichess-visible "narrow band"
the user originally observed and is **structurally fixable** via
optimistic-ponderhit emit logic.

Thread B work continues with corrected thresholds (initial Thread B
attempt had too-conservative depth/duration gates that rarely fired).

## Phase 5 branches (kept for archeology, all closed without merge)

- `experiment/tm-phase5a-widen-mid-cap`
- `experiment/tm-phase5b-raise-bmc-cap`
- `experiment/tm-phase5c-wide-cap-bmc`
- `experiment/tm-phase5d-sf-bmc`
- `experiment/tm-phase5e-lower-downward` (regressed -42 Elo)
- `experiment/tm-phase5f-gentle-downward` (regressed -49 Elo)

These can be deleted after some time. The analyzers
(`tm_position_aware.py`, `tm_autocorrelation.py`) and the engine survey
(`tm_phase5_engine_survey.md`) are the lasting deliverables.

## Lessons

1. **Pick the right metric first.** I spent days chasing max/p50 ratio
   before the user pointed out it was confounded by clock decay. The
   right metric (autocorrelation) immediately surfaced both the real
   gap (no-ponder 0.06) AND the right diagnosis (ponder-on 14× gap is
   the bigger issue).

2. **Beware proxy metrics from external observation.** SF's "bimodal
   distribution" in ponder-on RR was artifactually amplified by their
   optimistic ponderhit. Without controlling for that, all Phase 5a-d
   attempts targeted a non-existent gap.

3. **Architectural limits are real.** When five different parameter
   combinations all regress at the same rate per unit of metric
   improvement, the parameter direction is exhausted. Further effort
   needs a different architectural approach, not more knob-turning.
