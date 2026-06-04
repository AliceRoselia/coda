# Anti-Draw / Anti-Simplification Mechanisms — Cross-Engine Review (2026-06-04)

Comparative source + git-history review of 11 top engines (Stockfish, Reckless,
Obsidian, Alexandria, Integral, Viridithas, PlentyChess, Clover, Hobbes,
Koivisto, Velvet, Seer) for **code-level** techniques that avoid draws / avoid
over-simplification / press weaker opponents. Motivated by: codabot draws too
much vs weaker lichess opponents (settles into 3-fold reps and drawish
simplified positions), and our finding that **fixed draw-node contempt is
neutral-to-negative in fair RR** (see `memory/project_contempt_draw_avoidance`).

## What Coda ALREADY has (do not rebuild)

- **Material-based NNUE output scaling** — `src/search.rs:998`,
  `score × (22400 + material)/32/1024`, non-pawn material (N=422,B=422,R=642,
  Q=1015). Byte-identical to Alexandria `ScaleMaterial`, same structure as SF
  `evaluate.cpp:58-59`, Reckless `evaluation.rs:5`, Hobbes, Clover. Keeps eval
  magnitude tied to remaining material → resists trading into thin/drawn
  endings.
- **rule50 / 50-move eval damping** — `src/search.rs:1014`
  `apply_halfmove_scale`, `score × (100 − hm)/100`. MORE aggressive than SF
  (`/199`), Reckless/Alexandria (`/200`), Velvet (`/128`). Applied at point of
  use (avoids the TT-staleness bug, per the comment at `search.rs:989`).
- **Cuckoo upcoming-repetition** alpha-raise (currently to a hard `0`).

## Confirmed DEAD ENDS (don't pursue — tried/removed or absent everywhere)

- **rule50 as an NNUE input** — NONE of the 8 NNUE engines do this. All handle
  rule50 as a post-eval multiplicative scale. (Corrects an old CLAUDE.md note.)
- **Fortress detector / `winnable()` / opposite-colour-bishop scaleFactor** —
  absent in all modern code. Anti-fortress is EMERGENT from rule50 damping
  (SF commit `7b064752`: "SF will panic a little if there are >4 consecutive
  shuffling moves with an advantage… try to move a pawn or exchange to keep
  the advantage, so follow-ups are discovered earlier"). Obsidian's blocked-pawn
  dampening (`4a490f2`) and Koivisto's missing-pawn scaling (`c4de2aa4`) were
  both REMOVED.
- **Low-material→draw checks** — removed/neutral (Alexandria `2dcabb5`,
  Integral, PlentyChess).
- **WDL-as-eval-bias** — Integral & Viridithas WDL models are DISPLAY-ONLY
  (`info … wdl`), not fed back into search. (Seer reasons natively in
  WDL/logit space — but that's a full net retrain, a training-thread item.)
- **Separate draw head** — none.

## THE GAPS (ranked for Coda)

### 1. Optimism — the headline. ABSENT in Coda. HIGH promise.

Dynamic, root-score-derived eval bias, folded into eval with its own material
multiplier. **The mechanism SF built specifically after contempt failed for
NNUE** — our contempt-is-neutral result mirrors SF's, and optimism is their
answer.

- SF: compute `search.cpp:371-373` `optimism[us] = 137·avg/(|avg|+81)`,
  `optimism[~us] = −optimism[us]` (avg = root move running average score);
  apply `evaluate.cpp:55,59`: `optimism += optimism·nnueComplexity/476;`
  then `v = (nnue·(77871+material) + optimism·(7191+material))/77871`.
- Reckless (Rust sibling): `search.rs:116-117`
  `optimism[stm] = 159·best_avg/(|best_avg|+186)`; apply `evaluation.rs:5`
  `(raw·(20664+material) + optimism·(1487+material))/26685` then rule50 damp.
  Material-tunable change `63577436` SPRT'd **+1.86 STC / +5.43 LTC**.
- Viridithas `search.rs:352-354` (`128·avg/(|avg|+196)`) + apply `search.rs:1913`.
  PlentyChess `search.cpp:1439` (`150·mean/(|mean|+125)`) + `evaluation.cpp:46`.

Why it's different from the contempt we ruled out: average output unchanged;
proportional to the *actual* advantage; decays as position equalizes; modulates
keep-tension-vs-simplify, not draw inflation. **Shows in normal self-play
SPRT** (unlike contempt). **PlentyChess found material-scaling-alone neutral
until fused with optimism (`82271a4`→`7df1597`)** — Coda's solo material scaling
may be under-delivering for want of this partner.

Coda implementation sketch (Reckless-style, no complexity weighting for MVP):
- `SearchInfo { optimism: [i32; 2], … }` (init 0; reset 0 at search start).
- At root, each ID iteration: `let avg = best_root_avg_score;
  info.optimism[root_stm] = OPT_K*avg/(avg.abs()+OPT_OFF);
  info.optimism[1-root_stm] = -info.optimism[root_stm];`
  (needs a running average of the best root move's score — TM already tracks
  per-iteration best score; add the running mean.)
- At the eval-scale site `search.rs:998`, fold in optimism for `board.side_to_move`:
  `(score*(22400+material) + info.optimism[stm]*(OPT_BASE+material))/32/1024`.
- New tunables OPT_K (~150), OPT_OFF (~120), OPT_BASE (~1500).
- Validate: SPRT `[0,3]` (it DOES show in self-play), then retune-on-branch
  (tree-shape-changing eval). Complexity-weighting (SF) is a follow-up if the
  psqt/positional split is exposed by the v9 net.

### 2. Jittered draw score — cheap, attacks 3-fold settling directly. LTC-only.

Coda returns hard `0` at all draw/rep/50mr sites and raises cuckoo alpha to `0`.
Replace with a node-keyed jitter so the search prefers a non-repeating equal
line over locking onto a 3-fold.
- Koivisto `search.cpp:449`: `8 − (nodes & 15)` (±8 "Beal"), SPRT **+9.48
  ±5.98 Elo** (`c8f01211`).
- Alexandria `search.cpp:437`: `(nodes & 2) − 1` (±1) — **STC −1.11 (H0),
  LTC +2.05 (H1)** (`d22f597`). Velvet `(nodes&2)-1` shipped; Reckless
  `(nodes%5)-2` (±2) shipped as LTC non-reg; SF `±1` VLTC-only.
- ENGINE-DEPENDENT: Hobbes, Seer, Obsidian **tried and dropped** it.
- **LTC-positive, STC-negative** — almost certainly why Coda never found it.
  One-liner: `(info.nodes & 2) as i32 - 1` (or `(nodes % 5) - 2`, or Koivisto
  ±8) at the draw returns AND the cuckoo alpha-raise. **MUST SPRT at LTC**
  (40+0.4), test ±1 and ±8.

### 3. Cheap refinements / deployment backstop

- **SPSA-tunable material-scale base** — Integral `constants.h:102`
  `kMaterialScaleBase` (default 27600, range 10000–32768) vs Coda's hard-coded
  `22400`. Higher = less damping when winning down material. Expose + fold into
  next full SPSA. Trivial.
- **50mr-aware TT key** — Obsidian `search.cpp:502` / Integral `search.cc:279`
  / Reckless `board.rs:79` XOR a halfmove-clock bucket into the TT key so a
  low-clock "winning" entry isn't reused at a near-50mr-drawn position. Check
  whether Coda does this; correctness item, low convert-vs-weak promise.
- **Per-opponent eval-bias contempt** — Obsidian `ucioption.cpp:42-72`
  (`UCI_Opponent`-keyed `name=value` overrides) + asymmetric `±contempt` at
  EVERY node (`evaluate.cpp:13`, `!(ply%2)`), default 0. Deployment-only
  "press weaker opponents" lever that stays 0 in self-play (survives our
  fair-RR neutrality). The natural home for Coda's dormant `Contempt` knob IF
  optimism alone doesn't move lichess. Lower priority — optimism is the
  better-validated general version.

## Recommended sequence

1. **Optimism** (biggest gap, validated in Rust sibling, shows in SPRT) →
   SPRT `[0,3]` → SPSA optimism constants + adjacent eval-scale params (retune
   -on-branch).
2. **Jittered draw score** (separate branch) → SPRT at **LTC**, ±1 vs ±8.
3. Material-scale base → tunable, into the next full SPSA.
4. Per-opponent eval-bias contempt + dormant `Contempt` knob = deployment
   backstop if lichess still draws too much after 1–2.
