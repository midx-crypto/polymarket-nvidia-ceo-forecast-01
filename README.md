# Polymarket NVIDIA CEO Forecast — Adaptive Persistence Forecaster

Entry for make.fun `polymarket-nvidia-ceo-forecast-01`: forecast the Yes price
of every trading market of Polymarket's "Next CEO of NVIDIA?" event at every
minute of the 4 hours after each checkpoint, as five quantiles
[0.05, 0.25, 0.5, 0.75, 0.95].

## Program

`python3 main.py` (Python 3.13, standard library only, no network). It reads
every `<id>.in` in `$MAKEFUN_INPUT_DIR` (else `/input`) and writes
`<id>.out` to `$MAKEFUN_OUTPUT_DIR` (else `/output`).

## Model

Adaptive persistence, tuned on the kit's six practice cases (round 3):

- **Centre:** `0.7 * last price + 0.3 * previous price` — a one-step
  pullback toward the previous print — PLUS a level-dependent median drift
  ("frontrunner fade"): the median 4-hour move of a high-priced market is
  DOWN, because leaders' probability leaks away as new candidates enter and
  time passes. The fade is measured from the case's own history, not assumed:
  for each price-level bucket, the median of the standardised h-step changes
  (`d_h / sigma120(t)`, pooled over liquid times) is estimated per horizon
  and interpolated. The shift is shrunk by 0.75 and capped at +/-0.005, so
  the one case where the frontrunner surged instead (p02) only worsens by
  +0.0039.
- **Spread:** per-market sigma from the realised volatility of the last 120
  one-minute returns — short window, because volatility is strongly
  time-varying and long windows are poisoned by rare jumps — floored at
  0.0005 and capped at 0.01, growing like `h**0.32`, with base
  `z = [-2.2, -0.67449, 0, 0.67449, 2.2]` and the round-2 per-level
  asymmetry: x < 0.02 → (0.85, 1.30); x < 0.05 → (1.05, 1.00);
  x < 0.15 → (1.20, 0.85); x ≥ 0.15 → (1.35, 0.75). Clamped to `[0, 1]`,
  rounded to 6 decimals, non-decreasing per row.

## Practice score (local scorer, answers refetched from Polymarket's public
price history; reproduces the house baseline's 0.363589 exactly)

| entry | mean pinball loss | median error | 90% coverage |
|---|---|---|---|
| house baseline | 0.363589 | 0.767503 | 0.949642 |
| round 1 | 0.266819 | 0.767503 | 0.876139 |
| round 2 | 0.261907 | 0.758597 | 0.891504 |
| **this entry (round 3)** | **0.256110** | **0.733622** | **0.876074** |

Per case: p00 0.420716, p01 0.295710, p02 0.352219, p03 0.222619,
p04 0.194642, p05 0.111924 — better than the baseline on every case, better
than round 2 on 5 of 6 (only p02 is worse, +0.0039, bounded by the shift cap).
The median shift is a structural property, not a fit to the six answers:
its per-case medians are near-identical across all six cases (top bucket,
h=240: -0.70, -0.71, -0.60, -0.63, -0.57, -0.62), and leave-one-case-out
confirms the improvement in 5 of 6 folds with the shift parameter chosen on
the other five. Gains are balanced across halves (first half -0.0055/case,
second half -0.0061/case). Deterministic (two runs byte-identical); ~0.25 s
per case, far under the 8 s cap; largest output ~288 KB, under the 1 MiB cap.

## Alternatives tried and rejected (all measured on the same practice data)

Round 3 prize-zone work (`poly-work/exp18.py`–`exp28.py`):

- Vol-matched empirical quantiles (0.434–0.498) and standardised empirical
  quantiles (0.494): the empirical median is regime-biased; blends with
  round 2 (0.281–0.385) inherit the damage.
- OLS centre from drift / cross-market features (0.394–0.863): the apparent
  drift signal (corr -0.20) is entirely jump-driven (corr +0.004 once
  |d_h| > 0.05 moves are excluded) and the pooled intercept is a
  composition artefact (new markets entering), so the fitted centre is
  badly biased at the checkpoint.
- Per-level empirical z shapes (0.261–0.277): the spread shape is too noisy
  (outer quantiles up to -20 sigma units); only the MEDIAN of the
  distribution is stable across cases — hence this entry uses the median
  shift alone and keeps the Gaussian spread.
- Quantile-specific growth exponents (best split 0.2608), ensembles with
  round 2 / the round-3 near-miss (0.2601–0.2608), market-age features
  (no signal beyond sigma120), directional jump widening beyond round 2.
- Round-2 roundup (kept): alpha 0.32 alone 0.260549; asymmetric z alone
  0.2642; jump widening alone ~0.2601; the round-3 near-miss (alpha 0.32 +
  jump momentum + z_out 2.2) 0.259868 was rejected as noise (margin 0.000039
  over its threshold, three stacked knobs, mixed LOCO).
