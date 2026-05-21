# TM Phase 5 — Research Conclusion

**Date:** 2026-05-21
**TL;DR:** Phase 5 multiplier/cap experiments are null. Coda Phase 4 v2.1
(already in main) achieves SF-style variance **in no-ponder mode**. The
"narrow-band" lichess move-time pattern that motivated Phase 5 was an
artifact of comparing Coda's verify-always ponderhit behavior to top
engines' optimistic-ponderhit behavior, not a multiplier deficiency.

## Hypothesis (going in)

Lichess move-time graphs and ponder=on cutechess RR showed Coda's spend
clustering in a narrow band (CV 0.53, max/p50 ~6-8×) while
SF/Reckless/Obsidian appeared bimodal (CV 1.40, max/p50 ~22×).
Expectation: Coda's multipliers were under-expressive due to
- bmc_factor capped at 2.5
- per-change weight 0.25 (vs SF's 2.29)
- hard cap at 9-22% of remaining time (vs SF's ~81%)

Plan: widen the cap, raise/remove the bmc cap, adopt SF-style
coefficient. Phases 5a-5d ran each lever independently.

## What we tried

| Phase | Change | Cutechess RR result (vs main) |
|---|---|---|
| 5a | Wider mid/endgame hard cap (12-28%) | max/p50 7.3× vs main 7.9× — null |
| 5b | bmc_factor cap 2.5 → 6.0 | 5.0× vs 5.0× — null |
| 5c | 5a + 5b combined; hard cap to 50-75% of time | 6.1× vs 5.6× — null |
| 5d | 5c + SF-style bmc coefficient (×2 per change) | 9.2× vs 8.3× — marginal |

All four attempts produced essentially identical move-time distributions
to Phase 4 v2.1. Even Phase 5c's aggressive hard cap widening (8% →
60% pct_cap) didn't move the metrics, indicating the multipliers
weren't reaching the cap to begin with.

## What we discovered

User questioned whether the SF reference (max/p50 = 22× from the
180-game 4-engine RR at 120+1 ponder ON) was actually a valid target.
Re-ran the comparison **without pondering**:

| Engine | TC | p50 | p99 | max | **max/p50** |
|---|---|---|---|---|---|
| **Coda.main (Phase 4 v2.1)** | 120+1 no ponder | 2.00s | 10.18s | 24.00s | **12.0×** |
| Reckless | 120+1 no ponder | 2.20s | 17.00s | 29.00s | 13.2× |
| Stockfish | 120+1 no ponder | 2.00s | 13.14s | 28.00s | 14.0× |

**Coda already matches SF and Reckless within 15% on max/p50 in
no-ponder mode.** The 22× number we kept chasing was an artifact of
optimistic-ponderhit driving SF's p50 toward zero — pure mathematical
inflation of the ratio, not a position-aware-variance signal.

## Why all Phase 5 experiments were null

The multipliers ARE working correctly. Variance comes from genuine
position complexity signal (best-move stability, score trend, node
concentration). Coda's multipliers fire similarly to SF/Reckless on
the same kind of position. Caps/coefficients don't matter when the
underlying signal is similar.

The "narrow band" lichess users saw was Coda's verify-always
ponderhit forcing every non-ponderhit move to spend at least
~minimum-think time, while SF's optimistic-ponderhit emits many moves
at near-zero time. Compared side-by-side, Coda looks "uniform" but
the actual non-ponderhit spends are similarly varied.

## Conclusion

**Phase 5 (multiplier/cap redesign) is unnecessary.** Phase 4 v2.1
already achieves variance comparable to top engines in matched
conditions.

**The remaining lever is Thread B: optimistic ponderhit.** That's what
explains the asymmetry on lichess — not the cap widths or multiplier
coefficients. Pivoting all remaining TM work to Thread B.

## Lessons

1. **Validate metrics against the right baseline.** Comparing ponder-on
   to ponder-off engine behaviors mixes two different distributions
   and produces misleading targets.

2. **The smallest data-point can disprove a whole plan.** A single
   8-game no-ponder gauntlet falsified four prior implementation
   attempts.

3. **Coda's TM is actually competitive with the field already.** Phase
   2 (+4.5) and Phase 4 v2.1 (+3.3) banked the structural wins. What
   looked like a deficit in lichess production was the ponderhit
   architecture choice — orthogonal to TM widths/multipliers.

## What's in Phase 4 v2.1 (the production version)

For future reference, the merged state on main:
- Phase 1: bmc_factor multiplier (`1.0 + bmc/4.0).min(2.5)`)
- Phase 2: TC-aware hard cap brackets + minimum-reserve floor
- Phase 4 v2: ply-aware soft scaling (×0.4-1.0 by fullmove)
- Phase 4 v2.1: ply-aware hard cap scaling (same factors as soft)

Total banked: +7.8 Elo (4.5 + 3.3, both LTC SPRT validated).

## Phase 5 branches (kept for archeology)

All three pushed to origin, none merged:
- `experiment/tm-phase5a-widen-mid-cap` — null
- `experiment/tm-phase5b-raise-bmc-cap` — null
- `experiment/tm-phase5c-wide-cap-bmc` — null
- `experiment/tm-phase5d-sf-bmc` — null

These can be deleted after some time. The analyzer (`tm_position_aware.py`)
and survey doc (`tm_phase5_engine_survey.md`) remain useful.
