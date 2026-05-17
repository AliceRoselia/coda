# Mini-prod branch

Long-lived branch carrying trunk tunables SPSA-calibrated for the current
**baby-prod S200 net**, so that S200 experiment SPRTs measure pure
net/feature quality without tune-flation asymmetry.

Branch name stays `mini-prod` across baby-prod net rotations; the
current reference net is named in net.txt and a comment at the top of
the `tunables!` macro in `src/search.rs`.

See `docs/mini_prod_branch_workflow.md` for full methodology + the
canonical refresh procedure.

## Current state (2026-05-17, pre-retune)

- **Baby-prod net (net.txt)**: `cal-day0-factor-w15-warm30-hlcrelu-s200.nnue`
  (SHA `61115E7F`) — unchanged from prior refresh.
- **Last refresh**: 2026-05-17 — rebased onto main commit `1509806`
  (SMP bundle + cgu=16 + tune-1290 --core + Phase 3 ablation + core
  flag + binpack-stats anomaly-retention extension). S200-calibrated
  tunable values preserved from prior mini-prod for every tunable that
  exists on both sides; 10 renamed tunables (`_10X` migration) had
  values translated by ×10; 6 ablated tunables dropped. Focused --core
  retune pending to reconcile residual drift from structural changes.
- **Canonical bench (pre-retune)**: 4,307,652 (`make && ./coda bench`).
- **Previous refresh**: 2026-05-11 — established from main commit
  `6567cb8` with tune-#1092 outputs applied. Pre-rebase canonical
  bench was 4,006,126.

Update the section above on every refresh.

## TL;DR usage

**S200 experiments fork from here, not main:**

```bash
git checkout mini-prod
git checkout -b experiment/s200-<description>
# ... make S200 experimental changes ...
make && ./coda bench

OPENBENCH_PASSWORD=<pw> python3 scripts/ob_submit.py experiment/s200-<...> \
    --base-branch mini-prod --base-bench <mini-prod-bench> \
    --dev-network <CANDIDATE_SHA> --base-network 61115E7F
```

Both sides share S200-natively-tuned trunk → SPRT measures net/feature
delta, not tune-freshness asymmetry.

## Merge cadence (asymmetric — important)

- **To main**: H1 search/eval wins merge ASAP (normal SPRT cadence).
- **To mini-prod**: SAME wins propagate to mini-prod ONLY in scheduled
  refresh windows when **no S200 experiments are in flight**. Mid-flight
  base shifts invalidate in-progress mini-prod SPRTs.

So mini-prod intentionally lags main between refreshes. That's the
design, not a bug.

## When to trigger a refresh

Refresh mini-prod (rebase + retune) when ANY of:

1. Main has bumped the `tunables!` macro structure (added, removed,
   renamed, or widened range on a tunable).
2. Main landed a search-shape change (new pruning feature / gate /
   extension) that may interact with tuned values.
3. Main has accumulated **~5+ Elo** of merged changes since the last
   mini-prod refresh.
4. A new baby-prod net is deployed (different training methodology
   produces a new S200 reference) — note this is a **net rotation**,
   not a routine refresh; see `docs/mini_prod_branch_workflow.md`.

**Do not refresh during in-flight mini-prod experiments.** Pause until
they resolve.

## Refresh procedure (rebase + retune, agreed 2026-05-12)

```bash
git fetch origin
git checkout mini-prod
git pull origin mini-prod
git rebase origin/main

# Conflict resolution policy:
#   - Take main's STRUCTURAL changes (new/renamed tunables, new
#     features, widened ranges).
#   - Keep mini-prod's tuned VALUES for any tunable that exists on
#     both sides (those are S200-calibrated, not S800-calibrated).

make && ./coda bench   # record new bench

git commit -am "mini-prod: rebase onto main @ <main-sha>

Bench: <new-bench>"

# Focused full-sweep retune against the baby-prod net
OPENBENCH_PASSWORD=$OPENBENCH_PASSWORD python3 scripts/ob_tune.py mini-prod \
  --iterations 1500 --dev-network 61115E7F

# Wait for convergence (~few hours fleet), then apply outputs
curl -s -u <ob_creds> 'https://ob.atwiss.com/api/spsa/<TUNE_ID>/outputs/' \
  > /tmp/refresh.txt
python3 /tmp/apply_tune.py /tmp/refresh.txt
make && ./coda bench   # update the "Canonical bench" line above

git commit -am "mini-prod: apply tune-#<TUNE_ID> outputs

Bench: <new-bench>"

# Validate the refresh didn't regress
OPENBENCH_PASSWORD=$OPENBENCH_PASSWORD python3 scripts/ob_submit.py mini-prod \
  --base-branch <pre-refresh-mini-prod-sha> --bounds '[-3, 3]'

# On H1 or no-regression: push. On H0: investigate (likely SPSA noise
# or insufficient iter count).
git push origin mini-prod
```

Update the "Current state" section at the top of this file on every
refresh push.

## Baby-prod net rotation (different from refresh)

When training methodology produces a NEW S200 reference net (different
architecture / training recipe — not just a more-baked version of the
same net), archive the current mini-prod and start over:

```bash
git branch mini-prod-<old-net-shortname>-archive  # preserve history
git push origin mini-prod-<old-net-shortname>-archive
git checkout main
git branch -D mini-prod
git checkout main -b mini-prod
# Update net.txt to the new baby-prod
# Fire a fresh ~2500-iter full-sweep tune from main defaults
# ... apply, validate, push
```

Why rotation is different from refresh: the previous mini-prod tunings
were calibrated for the previous baby-prod's eval scale and shape. A
new baby-prod likely shifts the optimum enough that starting fresh is
cleaner than rebase+retune.
