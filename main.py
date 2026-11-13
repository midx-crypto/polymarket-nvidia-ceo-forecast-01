# polymarket-nvidia-ceo-forecast-01: adaptive persistence forecaster, round 3.
#
# Model (tuned on the kit's six practice cases, local loss 0.256077 vs the
# house baseline's 0.363589 and round 2's 0.261907, beating the baseline on
# every practice case and round 2 on 5 of 6):
#   - centre: 0.7 * last price + 0.3 * previous price (one-step pullback),
#     PLUS a level-dependent median drift ("frontrunner fade"): the median
#     4-hour move of a high-priced market is DOWN, because leaders' probability
#     leaks away as new candidates enter and time passes. The fade is measured
#     from the case's own history, not assumed: for each price-level bucket,
#     the median of the standardised h-step changes (d_h / sigma120(t), pooled
#     over liquid times) is estimated per horizon and interpolated. The shift
#     is shrunk by 0.75 and capped at +/-0.005, so the one case where the
#     frontrunner surged instead (p02) only worsens by +0.0039.
#   - spread: per-market sigma from the realised volatility of the last 120
#     one-minute returns, floored at 0.0005 and capped at 0.01, growing like
#     h**0.32; quantiles centre + z_tau * sigma * h**0.32 with base
#     z = [-2.2, -0.67449, 0, 0.67449, 2.2] and the round-2 per-level
#     asymmetry (down/up multipliers per last-price bucket).
#
# What was tried and rejected in the prize-zone round (all on the same
# practice data, same scorer): vol-matched empirical quantiles (0.434-0.498),
# standardised empirical quantiles (0.494), blends with round 2 (0.281-0.385),
# OLS centre from drift/cross-market features (0.394-0.863; the apparent drift
# signal is entirely jump-driven and the pooled intercept is a composition
# artefact), per-level empirical z shapes (0.261-0.277; the spread shape is
# too noisy, only the MEDIAN of the distribution is stable), alpha splits
# (best 0.2608), ensembles with round 2 / the round-3 near-miss (0.2601-0.2608).
# The median shift is the only new family that cleared every gate, and its
# per-case medians are near-identical across all six cases (top bucket, h=240:
# -0.70, -0.71, -0.60, -0.63, -0.57, -0.62), so it is a structural property of
# the price process, not a fit to the six answers.
#
# Python 3.13, standard library only, no network, deterministic.

import json
import math
import os
from pathlib import Path

INPUT_DIR = os.environ.get("MAKEFUN_INPUT_DIR", "/input")
OUTPUT_DIR = os.environ.get("MAKEFUN_OUTPUT_DIR", "/output")

QUANTILES = [0.05, 0.25, 0.5, 0.75, 0.95]
VOL_WINDOW = 120          # minutes of recent 1-min returns used for sigma
SIGMA_FLOOR = 0.0005      # never forecast a dead-quiet market as frozen
SIGMA_CAP = 0.01          # one jump must not blow the spread up
ALPHA = 0.32              # spread growth exponent in horizon h
Z_OUT = 2.2               # outer quantile multiplier
Z_IN = 0.67449            # inner quantile multiplier
# Centre weights, newest first: 0.7 * last price + 0.3 * previous price.
CENTRE_W = (0.7, 0.3)
# (x_lo, down_mult, up_mult): first row whose x_lo <= x wins.
ASYM_ROWS = (
    (0.0, 0.85, 1.30),
    (0.02, 1.05, 1.00),
    (0.05, 1.20, 0.85),
    (0.15, 1.35, 0.75),
)
# Median-shift parameters: shrink and absolute cap on the centre shift.
SHIFT_SHRINK = 0.75
SHIFT_CAP = 0.005
# Horizons at which the per-level median standardised change is estimated
# from the market's own history (interpolated linearly in between).
SHIFT_HGRID = (1, 2, 3, 5, 8, 13, 21, 34, 55, 89, 144, 233, 240)
SHIFT_ALPHA = 0.35        # standardisation exponent for the median estimate
SHIFT_MIN_T = 300         # earliest time index used for the history sample
SHIFT_MIN_N = 200         # minimum samples per (bucket, horizon); else 0
LIQ_SIGMA_MIN = 0.001     # a time counts as liquid only if sigma120 >= this
LIQ_MIN_MOVES = 3         # ... and at least this many nonzero 1-min returns
                          # in the trailing 120 minutes


def price6(x):
    """Clamp to [0, 1] and round to 6 decimals (0, never -0)."""
    return round(min(1.0, max(0.0, x)) * 1e6) / 1e6 + 0.0


def _median(sorted_vals):
    n = len(sorted_vals)
    if n == 0:
        return 0.0
    mid = n // 2
    if n % 2:
        return sorted_vals[mid]
    return 0.5 * (sorted_vals[mid - 1] + sorted_vals[mid])


def _bucket(x):
    b = 0
    for i, (lo, _d, _u) in enumerate(ASYM_ROWS):
        if x >= lo:
            b = i
    return b


def _rolling_stats(prices):
    """Per price index t: (sigma120(t), liquid(t)).

    sigma120(t) is the population std of the 1-minute returns ending at t
    (last 120 returns, fewer if the market is younger, NaN if fewer than 5).
    liquid(t) is True when sigma120(t) >= LIQ_SIGMA_MIN and at least
    LIQ_MIN_MOVES of those returns are nonzero.
    """
    n = len(prices)
    rets = [prices[i + 1] - prices[i] for i in range(n - 1)]
    # Prefix sums for O(1) window mean/var and nonzero counts.
    ps = [0.0]
    ps2 = [0.0]
    pnz = [0]
    for r in rets:
        ps.append(ps[-1] + r)
        ps2.append(ps2[-1] + r * r)
        pnz.append(pnz[-1] + (1 if r != 0.0 else 0))
    sigma = [None] * n
    liquid = [False] * n
    for t in range(n):
        k = t if t < VOL_WINDOW else VOL_WINDOW
        if k < 5:
            continue
        cnt = k
        s = ps[t] - ps[t - k]
        s2 = ps2[t] - ps2[t - k]
        mean = s / cnt
        var = s2 / cnt - mean * mean
        sig = math.sqrt(var) if var > 0.0 else 0.0
        sigma[t] = sig
        nz = pnz[t] - pnz[t - k]
        liquid[t] = sig >= LIQ_SIGMA_MIN and nz >= LIQ_MIN_MOVES
    return sigma, liquid


def median_shift_curves(markets):
    """Per price-level bucket, the median standardised h-step change at each
    horizon in SHIFT_HGRID, estimated from ALL markets' histories pooled
    (each market contributes the times its own price sat in that bucket).

    Returns a list of 4 lists (one per bucket) of len(SHIFT_HGRID) medians.
    A bucket/horizon with too few liquid samples yields 0.0 (no shift).
    Times are aligned on the case checkpoint: every market ends at the same
    minute, so a market of length n in a case of max length T starts at
    global time T - n, and only global times >= SHIFT_MIN_T are sampled.
    """
    t_max_case = max(len(m["prices"]) for m in markets)
    curves = [[0.0] * len(SHIFT_HGRID) for _ in range(len(ASYM_ROWS))]
    # Precompute rolling stats per market once.
    prepared = []
    for m in markets:
        prices = m["prices"]
        sigma, liquid = _rolling_stats(prices)
        prepared.append((prices, sigma, liquid, t_max_case - len(prices)))
    for hi, h in enumerate(SHIFT_HGRID):
        inv = h ** (-SHIFT_ALPHA)
        buckets = [[] for _ in range(len(ASYM_ROWS))]
        for prices, sigma, liquid, offset in prepared:
            n = len(prices)
            t_max = n - 1 - h
            start = SHIFT_MIN_T - offset
            if start < 0:
                start = 0
            if t_max <= start:
                continue
            t = start
            while t <= t_max:
                if liquid[t]:
                    s = sigma[t]
                    if s is not None and s > 1e-5:
                        d = prices[t + h] - prices[t]
                        buckets[_bucket(prices[t])].append((d / s) * inv)
                t += 2
        for b in range(len(ASYM_ROWS)):
            vals = buckets[b]
            if len(vals) >= SHIFT_MIN_N:
                vals.sort()
                curves[b][hi] = _median(vals)
    return curves


def interp_grid(grid, xs, x):
    """Linear interpolation of grid (values at xs) at x (clamped ends)."""
    if x <= xs[0]:
        return grid[0]
    if x >= xs[-1]:
        return grid[-1]
    lo, hi = 0, len(xs) - 1
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if xs[mid] <= x:
            lo = mid
        else:
            hi = mid
    x0, x1 = xs[lo], xs[hi]
    y0, y1 = grid[lo], grid[hi]
    return y0 + (y1 - y0) * (x - x0) / (x1 - x0)


def market_sigma(prices):
    """Std of the 1-minute returns over the last VOL_WINDOW minutes."""
    n = len(prices)
    if n < 3:
        return SIGMA_FLOOR
    start = max(1, n - VOL_WINDOW)
    diffs = [prices[i] - prices[i - 1] for i in range(start, n)]
    m = len(diffs)
    mean = sum(diffs) / m
    var = sum((d - mean) ** 2 for d in diffs) / m
    sigma = math.sqrt(var)
    return min(max(sigma, SIGMA_FLOOR), SIGMA_CAP)


def asym_multipliers(x):
    """(down_mult, up_mult) for a market whose last price is x."""
    down, up = ASYM_ROWS[0][1], ASYM_ROWS[0][2]
    for lo, d, u in ASYM_ROWS:
        if x >= lo:
            down, up = d, u
    return down, up


def forecast_market(market, horizon, shift_curves):
    prices = market["prices"]
    if not prices:
        raise ValueError(f"market {market['id']} has no prices")
    x = prices[-1]
    # Centre: weighted average of the last two prints (pullback toward the
    # previous print); a single print falls back to the last price.
    if len(prices) >= 2:
        centre0 = CENTRE_W[0] * prices[-1] + CENTRE_W[1] * prices[-2]
    else:
        centre0 = x
    sigma = market_sigma(prices)
    down, up = asym_multipliers(x)
    z = [(-Z_OUT) * down, (-Z_IN) * down, 0.0, Z_IN * up, Z_OUT * up]
    # Median drift ("frontrunner fade") from the case's pooled history.
    zmed = shift_curves[_bucket(x)]
    rows = []
    for h in range(1, horizon + 1):
        grow = h ** ALPHA
        shift = SHIFT_SHRINK * interp_grid(zmed, SHIFT_HGRID, h) * sigma * grow
        if shift > SHIFT_CAP:
            shift = SHIFT_CAP
        elif shift < -SHIFT_CAP:
            shift = -SHIFT_CAP
        centre = centre0 + shift
        spread = sigma * grow
        row = [price6(centre + zj * spread) for zj in z]
        # Rounding/clamping cannot break order here (z is ascending), but
        # enforce non-decreasing explicitly so the output is always valid.
        for j in range(1, len(row)):
            if row[j] < row[j - 1]:
                row[j] = row[j - 1]
        rows.append(row)
    return {"id": market["id"], "q": rows}


def main():
    in_dir = Path(INPUT_DIR)
    out_dir = Path(OUTPUT_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    inputs = sorted(p for p in in_dir.iterdir() if p.name.endswith(".in"))
    for path in inputs:
        case_id = path.name[: -len(".in")]
        case = json.loads(path.read_text(encoding="utf-8"))
        if case["quantiles"] != QUANTILES:
            raise ValueError(
                f"{path.name} asks for quantiles {case['quantiles']}, "
                f"not {QUANTILES}"
            )
        horizon = case["horizon_minutes"]
        shift_curves = median_shift_curves(case["markets"])
        forecasts = [
            forecast_market(m, horizon, shift_curves) for m in case["markets"]
        ]
        text = json.dumps({"forecasts": forecasts}) + "\n"
        if len(text.encode("utf-8")) > 1_048_576:
            raise ValueError(f"{case_id}.out would exceed the 1 MiB cap")
        out_path = out_dir / f"{case_id}.out"
        out_path.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
