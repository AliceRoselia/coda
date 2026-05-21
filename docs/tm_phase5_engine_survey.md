# TM Phase 5 — Engine Survey (9 engines)

Comparison of time-management implementations across the top open-source
engines to inform Coda Phase 5 TM redesign. Survey conducted 2026-05-21.

## Comparison table

| Engine | Soft formula | Hard formula | Phase-aware? | Multipliers | Multiplier combo | Ponderhit |
|---|---|---|---|---|---|---|
| **Stockfish** | Power-law `(ply+3.227)^0.47 × c` + log(timeLeft) | ~0.81 × time, scales `6.87+ply/12.35` | **Yes** (ply) | 0 (pure time alloc) | N/A | Wait for GUI; sets `stopOnPonderhit` |
| **Reckless** | `0.066 − 0.042·exp(−0.045·fullmove)` × time + 0.75·inc | 0.742 × time + 0.75·inc | **Yes** (fullmove) | 1 external (caller-supplied) | Search supplies factor | Not visible (search-layer) |
| **Hobbes** | Identical to Reckless | Identical to Reckless | **Yes** (fullmove) | 3 (stability, score, node) | Product, ranges 0.88×–1.8× each | Not visible |
| **Obsidian** | `min(0.025, 0.214 × time/timeLeft)` | 0.80 × time | No | 0 | N/A | Not visible |
| **Alexandria** | `min(0.90/mtg, 0.88·time/timeLeft)` × tuned | 0.76 × time | No | 3 (stability, eval, node) | Product | Not visible |
| **Integral** | `min(0.4193·time_left, 0.0575·total)` | `min(0.9221·time − overhead, 5.928 × soft)` | **Via multipliers** | 3 (8 tuned params) | Product, gated at depth ≥ 6 | Not visible |
| **Viridithas** | Configurable `optimal_window_frac × computed` | 46% of clock | **Yes** (4 multipliers) | **4** (stability, fail-low, forced-move, node-subtree) | Product | **Hard = soft** on ponder ← aggressive |
| **PlentyChess** | `0.8463 × totalTime` (tuned, disabled) | `min(0.729 × time, 2.81 × totalTime)` | No | 1 external | External factor | Treated as normal search |
| **Clover** | Dual `endtime1` (soft) and `endtime2` (hard) | f1/f2 ratios with phase | **Yes** (phase + fullmove) | 1 `constance` | Modulates f1/f2 | **Bonus**: ponderhit increases `constance` |

## Per-engine highlights

(See agent report for full detail. Key takeaways below.)

### Stockfish
- Power-law growth with ply: `optScale = 0.012 + (ply+3.227)^0.47 × c` — soft target ~2× larger in middlegame than opening
- Hard cap ~81% of time. No dynamic multipliers — relies on pure time allocation + search quality
- Ponderhit: never optimistic-emits; waits for GUI ponder exit

### Reckless
- Exponential growth: soft scales from 2.4% → 6.6% of time over fullmove (asymptote at fullmove ≈ ∞)
- Hard fixed at 74.2% of time + 75% of inc — wide ceiling allows multiplier expression
- Search-layer supplies multiplier callback — TM module is stateless on multipliers

### Hobbes
- Identical Reckless's soft/hard formulas (credits Reckless in code comments)
- Adds 3-factor product: stability `max(0.9, 1.8−0.1·stab)`, score `max(0.88, 1.2−0.04·stab)`, node `(1.5−frac)×1.35`
- Stability multiplier converges fast: `max(0.9, 1.8−0.1·stab)` — at stab=9, factor=0.9 (vs Coda's `max(0.5, 1.71−0.08·stab)` reaching 0.91 only at stab=10)

### Viridithas
- **Lookup table for stability**: `[2.50, 1.20, 0.90, 0.80, 0.75]` — converges in 1-2 iterations vs Coda's gradual linear decay
- **4 multipliers**: stability × fail-low × forced-move × node-subtree
- **Ponderhit clamps hard = soft** — aggressive early-emit on ponder hit
- Forced-move detector: drops time to 1% (one-legal) / 38.6% (strong forced) / 62.7% (weak forced)
- Per-mille tunable constants — heavy SPSA optimization

### Integral
- 8 SPSA-tuned constants
- **Depth ≥ 6 gating**: below depth 6, only hard limit fires; soft TM disabled until depth 6 reached
- Multiplier formulas track `(score_depth_3 - score_current)` and `(prev_score - score_current)` for volatility signal

### Clover
- Two-time design (soft `endtime1`, hard `endtime2`) instead of soft + product multiplier
- **Ponderhit as time bonus**: `ponderhitbonus = 4 if predicted`, reduces divisor → more time
- Phase via material+fullmove hybrid

### Obsidian / Alexandria / PlentyChess
- Less sophisticated — simpler soft/hard with external multiplier callbacks
- Obsidian especially minimalist (no multipliers visible in header)

## Patterns observed

1. **Phase-aware scaling is consensus**: Stockfish (ply power-law), Reckless/Hobbes (fullmove exponential), Viridithas (multiplicative), Clover (phase+moves), Integral (depth-gated). Only Obsidian, Alexandria, PlentyChess use flat budgets.

2. **3-factor product is the multiplier consensus**: Hobbes/Alexandria/Integral all use product of (stability, score-related, node-fraction). Coda already follows this with 4-factor (bmc + stability + score + nodes), so we're on the right pattern.

3. **Stability convergence is faster in top engines**:
   - **Viridithas**: `[2.50, 1.20, 0.90, 0.80, 0.75]` — settles in 2 iterations
   - **Hobbes**: `max(0.9, 1.8−0.1·stab)` — at stab=2, factor=1.6
   - **Coda**: `max(0.5, 1.71−0.08·stab)` — at stab=2, factor=1.55 (similar); but cap floor of 0.5 reached only at stab=15
   - Coda's curve is similar early but doesn't drop as low — top engines emit faster when fully stable

4. **Bimodal multiplier behavior**:
   - Viridithas's lookup table is the cleanest example: 2.50× (unstable) → 0.75× (stable) is a clear bimodal split
   - Coda's smooth linear from 1.71 → 0.5 is more gradual
   - Hobbes is in between

5. **Hard limit width varies widely**:
   - Tightest: Viridithas 46%, Alexandria 76%, Obsidian 80%
   - Widest: Stockfish ~81%, Integral 92.2%
   - Coda Phase 2: 9-15% (pct_cap-based) — much tighter than all of these
   - The wide-hard-cap engines achieve bimodal variance by letting multipliers actually express in absolute spend

6. **Ponderhit handling is most varied**:
   - **Wait** (Stockfish): conservative, lets ponder finish
   - **Optimistic emit / hard=soft** (Viridithas): aggressive, banks the ponder time
   - **Bonus** (Clover): ponderhit increases time budget for current move
   - No engine uses the "always verify with min think" pattern Coda currently does

## Implications for Coda Phase 5

### Thread A (non-ponder variance):

1. **Widen middlegame hard cap** — Coda's 9-22% is the tightest in the field. Wider is consensus (74-92%). Combined with our Phase 4 v2.1 opening discipline, we can go much wider in middlegame safely.

2. **Faster stability convergence** — replace `1.71 - 0.08·stab` with a faster-converging shape, perhaps lookup-table like Viridithas. Lets the engine emit "stable" moves more decisively, freeing time for tactical positions.

3. **Consider raising bmc cap or removing it** — Viridithas's effective unstable multiplier (stab=0 → 2.50) is similar to our bmc cap (2.5). But combined with their wider hard cap, multipliers actually express bigger spends. Our 2.5 cap with our tight hard creates the "smooth curve" pattern.

4. **Forced-move detector** (Viridithas pattern) — a "this is the only good move" signal could drastically reduce spend on book-exit captures and clear recaptures. Big variance lever.

5. **The "exponential fullmove" soft growth** (Reckless/Hobbes) is structurally cleaner than our piecewise-linear phase factor. Worth considering as a Phase 5 refactor.

### Thread B (smart ponderhit):

1. **Viridithas pattern**: `hard_time = opt_time` on ponderhit — clamps to soft, allows quick exit if soft elapsed
2. **Clover pattern**: ponderhit → time bonus, search continues but with extra budget
3. **The combination we sketched** (depth threshold + ponder duration + time pressure) doesn't directly match any single engine but is closest to Viridithas's "trust the ponder result" philosophy
