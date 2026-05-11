# Mini-prod (cal-day0 S200) branch

A long-lived branch that serves as the **tuned baseline** for S200 model
experiments. Forking S200 experiments from `main` (which is tuned for the
prod SB800 net) gives the experimental side a "free" tune-flation advantage
of 5-15 Elo from the freshness asymmetry; forking from this branch removes
that artifact.

## Branch contents (2026-05-11)

- **Base commit**: forked from `main` after `_10X` migration (commit
  `6567cb8`) + 12-tunable `_10X` batch + NMP_EVAL_MAX=2 bisect.
- **Net (net.txt)**: `cal-day0-factor-w15-warm30-hlcrelu-s200.nnue`
  (SHA `61115E7F`, uploaded to v0.4.0-nets release).
- **Tunables**: tune-#1092 outputs applied (1500-iter focused sweep against
  cal-day0 net). 52 default changes from trunk-prod equilibrium.
- **Canonical bench**: **4,006,126** (`make && ./coda bench`).

## When to use this branch as a base

- Any S200 model-vs-model SPRT (e.g. comparing two SB200 candidate nets).
- Any net-architecture probe trained to ~SB200 (factor variants, hidden-
  layer shape, threat-feature changes) where you want a tuned-vs-tuned
  comparison instead of tuned-vs-untuned.

## When NOT to use it

- Production deployment: this branch is for S200 baseline only. Prod
  uses `main` with the SB800 net.
- SB800 experiments: use `main`. Mini-prod's tune outputs are for the S200
  eval scale, not SB800.

## Refresh procedure

Refresh whenever a substantive search/eval change lands on `main`:

```bash
git checkout mini-prod-cal-day0-s200
git rebase main                          # carry _10X + bisect updates forward
# Resolve any conflicts (rare — tunable defaults).

# Re-tune against cal-day0 S200 net via OB:
OPENBENCH_PASSWORD=<pw> python3 scripts/ob_tune.py mini-prod-cal-day0-s200 \
    --iterations 1500 --dev-network 61115E7F

# Apply outputs once the tune converges:
curl -s -u <ob_creds> 'https://ob.atwiss.com/api/spsa/<TUNE_ID>/outputs/' > /tmp/refresh.txt
python3 /tmp/apply_tune_outputs.py /tmp/refresh.txt src/search.rs
make && ./coda bench    # update the canonical bench number above

git commit -am "mini-prod: rebase + retune (tune #<TUNE_ID>)"
git push origin mini-prod-cal-day0-s200
```

Document each refresh in the trailer of the commit message and update
the "Branch contents" section here with the new bench number.

## How to launch S200 experiments off this branch

```bash
git checkout mini-prod-cal-day0-s200
git checkout -b experiment/s200-<description>
# Make your S200 experimental changes (apply alternative net via net.txt
# or train-time architectural changes etc.)

# SPRT against mini-prod baseline:
OPENBENCH_PASSWORD=<pw> python3 scripts/ob_submit.py experiment/s200-<...> \
    --base-branch mini-prod-cal-day0-s200 \
    --dev-network <CANDIDATE_SHA> \
    --base-network 61115E7F
```

Both sides run with the same S200 baseline tunables but their respective
nets, so the SPRT measures pure net-quality difference, not tune-flation
asymmetry.

## Provenance

- Established 2026-05-11 from main commit `6567cb8`.
- Tune #1092 applied (cal-day0 net, 1500 iter, focused sweep on prod
  tunable cluster).
- See `docs/mini_prod_branch_workflow.md` for the methodology discussion.
