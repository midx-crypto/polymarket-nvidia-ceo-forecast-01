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

Adaptive persistence, tuned on the kit's six practice cases:

- **Median:** the market's last price. Any drift or smoothing of the centre
  made practice worse.
- **Spread:** per-market sigma from the realised volatility of the last 120
  one-minute returns — short window, because volatility is strongly
  time-varying and long windows are poisoned by rare jumps — floored at
  0.0005 and capped at 0.01, growing like `h**0.35` (sub-diffusive: prices
  are steppy and jump-then-revert, so the spread saturates instead of
  following `sqrt(h)`).
- **Quantiles:** `x + z_tau * sigma * h**0.35` with heavy outer tails
  `z = [-2.1, -0.67449, 0, 0.67449, 2.1]`, clamped to `[0, 1]`, rounded to
  6 decimals, non-decreasing per row.

## Practice score (local scorer, answers refetched from Polymarket's public
price history; reproduces the house baseline's 0.363589 exactly)

| entry | mean pinball loss | median error | 90% coverage |
|---|---|---|---|
| house baseline | 0.363589 | 0.767503 | 0.949642 |
| this entry | **0.266819** | 0.767503 | 0.876139 |

Per case: p00 0.464932, p01 0.312366, p02 0.338474, p03 0.230999,
p04 0.202118, p05 0.116223 — better than the baseline on every case.
Deterministic (two runs byte-identical); ~0.05 s per case, far under the
8 s cap; largest output ~279 KB, under the 1 MiB cap.

## Alternatives tried and rejected (all measured on the same practice data)

- Empirical h-step change quantiles (full 72 h / 24 h / 12 h): 0.365–0.378.
- Gaussian with 24 h / 72 h realised vol: 0.65 / 0.73 (jump-poisoned).
- EWMA vol, MAD/robust sigma, winsorised sigma: no better than plain std
  on the last 120 min.
- Drift from recent trend (shrink 0.1–0.5): worse.
- Median mean-reversion toward the trailing mean: worse.
- Centre = median of last 3–60 min prices: worse.
- Spread growth `sqrt(h)` (alpha 0.5): 0.348; alpha 0.35 is the sweet spot.
