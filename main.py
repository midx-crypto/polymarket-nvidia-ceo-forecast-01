# polymarket-nvidia-ceo-forecast-01: adaptive persistence forecaster.
#
# Model (tuned on the kit's six practice cases, loss 0.266819 vs the house
# baseline's 0.363589, beating it on every practice case):
#   - median: the market's last price (persistence; any drift or smoothing of
#     the centre made practice worse).
#   - spread: per-market sigma from the realised volatility of the last 120
#     one-minute returns (short window: volatility is strongly time-varying
#     and long windows are poisoned by rare jumps), floored at 0.0005 and
#     capped at 0.01, growing like h**0.35 (sub-diffusive: prices are steppy
#     and jump-then-revert, so the spread saturates instead of sqrt(h)).
#   - quantiles: x + z_tau * sigma * h**0.35 with heavy outer tails
#     z = [-2.1, -0.67449, 0, 0.67449, 2.1] (jumps punish narrow tails),
#     clamped to [0, 1] and rounded to 6 decimals.
#
# Python 3.13, standard library only, no network, deterministic.

import json
import math
import os
from pathlib import Path

INPUT_DIR = os.environ.get("MAKEFUN_INPUT_DIR", "/input")
OUTPUT_DIR = os.environ.get("MAKEFUN_OUTPUT_DIR", "/output")

QUANTILES = [0.05, 0.25, 0.5, 0.75, 0.95]
# Standard-normal quantiles at the five levels, with the outer pair widened
# to 2.1 for jump-heavy tails (tuned on practice; 2.0/2.2 are within noise).
Z = [-2.1, -0.67449, 0.0, 0.67449, 2.1]
VOL_WINDOW = 120          # minutes of recent 1-min returns used for sigma
SIGMA_FLOOR = 0.0005      # never forecast a dead-quiet market as frozen
SIGMA_CAP = 0.01          # one jump must not blow the spread up
ALPHA = 0.35              # spread growth exponent in horizon h


def price6(x):
    """Clamp to [0, 1] and round to 6 decimals (0, never -0)."""
    return round(min(1.0, max(0.0, x)) * 1e6) / 1e6 + 0.0


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


def forecast_market(market, horizon):
    prices = market["prices"]
    if not prices:
        raise ValueError(f"market {market['id']} has no prices")
    x = prices[-1]
    sigma = market_sigma(prices)
    rows = []
    for h in range(1, horizon + 1):
        spread = sigma * (h ** ALPHA)
        row = [price6(x + z * spread) for z in Z]
        # Rounding/clamping cannot break order here (Z is ascending), but
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
        forecasts = [
            forecast_market(m, horizon) for m in case["markets"]
        ]
        text = json.dumps({"forecasts": forecasts}) + "\n"
        if len(text.encode("utf-8")) > 1_048_576:
            raise ValueError(f"{case_id}.out would exceed the 1 MiB cap")
        out_path = out_dir / f"{case_id}.out"
        out_path.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
