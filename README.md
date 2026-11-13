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

Adaptive persistence, tuned on the kit's six practice cases (round 2):

- **Centre:** `0.7 * last price + 0.3 * previous price` — a one-step
  pullback toward the previous print. Prices jump then partly revert, so
  the last print alone overshoots; a plain median of the last 3–60 prices
  was worse, but this 2-print weighted centre helps (median error
  0.7675 → 0.7586).
- **Spread:** per-market sigma from the realised volatility of the last 120
  one-minute returns — short window, because volatility is strongly
  time-varying and long windows are poisoned by rare jumps — floored at
  0.0005 and capped at 0.01, growing like `h**0.35` (sub-diffusive: prices
  are steppy and jump-then-revert, so the spread saturates instead of
  following `sqrt(h)`).
- **Quantiles:** `centre + z_tau * sigma * h**0.35`, where the z multipliers
  are asymmetric by price level: low-priced markets are floored at 0 and
  jump up, so their upper tail is wider; high-priced markets drift down
  over the window, so their lower tail is wider. Rows (last price x →
  down/up multiplier): x < 0.02 → (0.85, 1.30); x < 0.05 → (1.05, 1.00);
  x < 0.15 → (1.20, 0.85); x ≥ 0.15 → (1.35, 0.75). The asymmetry applies
  to the outer and inner quantiles alike. Base
  `z = [-2.1, -0.67449, 0, 0.67449, 2.1]`, clamped to `[0, 1]`, rounded to
  6 decimals, non-decreasing per row.

## Practice score (local scorer, answers refetched from Polymarket's public
price history; reproduces the house baseline's 0.363589 exactly)

| entry | mean pinball loss | median error | 90% coverage |
|---|---|---|---|
| house baseline | 0.363589 | 0.767503 | 0.949642 |
| round 1 | 0.266819 | 0.767503 | 0.876139 |
| this entry (round 2) | **0.261907** | 0.758597 | 0.891504 |

Per case: p00 0.438395, p01 0.298254, p02 0.348363, p03 0.229474,
p04 0.200893, p05 0.117064 — better than the baseline on every case
(and better than round 1 on 4 of 6; p02 is 0.0099 worse than round 1,
driven by a single high-priced market that jumped up in that case, while
the same market fell hard in p00). Round 2 beats round 1 in every
leave-one-case-out fold and across the whole neighbourhood of nearby
parameterisations (0.2619–0.2626), so the gain is a stable plateau, not
a knife-edge fit.
Deterministic (two runs byte-identical); ~0.05 s per case, far under the
8 s cap; largest output ~280 KB, under the 1 MiB cap.

## Alternatives tried and rejected (all measured on the same practice data)

- Empirical h-step change quantiles (full 72 h / 24 h / 12 h): 0.365–0.378.
- Gaussian with 24 h / 72 h realised vol: 0.65 / 0.73 (jump-poisoned).
- EWMA vol, MAD/robust sigma, winsorised sigma: no better than plain std
  on the last 120 min.
- Drift from recent trend (shrink 0.1–0.5): worse.
- Median mean-reversion toward the trailing mean: worse.
- Centre = median of last 3–60 min prices: worse.
- Spread growth `sqrt(h)` (alpha 0.5): 0.348; alpha 0.35 is the sweet spot.
- Blending 120-min sigma with 24 h vol (weight 0.1–0.5): 0.280–0.388.
- Sigma floor/cap grid: no better than floor 0.0005 / cap 0.01.
- Per-market alpha from return autocorrelation: 0.269.
- Widening outer tails by jump frequency: 0.304–0.409.
- Median decay toward 0 / linear drift: 0.265 at best, then much worse.
- Round-2 roundup: global asymmetric z alone 0.2642; price-bucketed
  asymmetry + weighted centre 0.2619 (this entry).
