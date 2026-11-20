"""Path generators. Each returns rel: (n, T, 4) bars as o,h,l,c ratios to the
previous bar's close, for bars k+1..last (T = last - k).

Models differ on purpose; their disagreement is part of the report.

bar_bootstrap    each bar drawn independently from past sessions' bar at the same
                 time of day (+/- `window` slots). Same idea as trader-timemachine.
                 Keeps the intraday volatility profile, loses autocorrelation.
block_bootstrap  contiguous blocks of `block_size_bars` bars copied from one past
                 session at the same time of day. Keeps short-range momentum /
                 mean reversion and volatility clustering inside a block.
gbm              zero-drift geometric Brownian motion (price is a martingale) with
                 the per-slot volatility of the pool. Intrabar high/low drawn from
                 the exact Brownian-bridge max/min distribution. The "no edge"
                 baseline: if a plan only looks good under bootstrap, the edge is
                 coming from the pool's specific history.
regime_shock     block_bootstrap with log moves scaled by `vol_multiplier`, plus,
                 with probability `gap_prob` per path, one adverse gap of
                 `gap_size_r` x risk at a random bar. A stress test, not a forecast.
"""

import numpy as np

MODELS = ("bar_bootstrap", "block_bootstrap", "gbm", "regime_shock")
_MODEL_ID = {m: i for i, m in enumerate(MODELS)}


def rng_for(seed, model):
    """Independent, order-free stream per model: adding a model never changes another's numbers."""
    return np.random.default_rng([int(seed), _MODEL_ID[model]])


def _slots(k, last):
    return np.arange(k + 1, last + 1)


def bar_bootstrap(pool, k, last, n, rng, window=2, **_):
    S, B = pool.shape[0], pool.shape[1]
    slots = np.broadcast_to(_slots(k, last), (n, last - k))
    if window:
        slots = np.clip(slots + rng.integers(-window, window + 1, size=slots.shape), 1, B - 1)
    sess = rng.integers(0, S, size=slots.shape)
    return pool[sess, slots]


def block_bootstrap(pool, k, last, n, rng, block_size_bars=6, **_):
    S = pool.shape[0]
    T = last - k
    b = max(1, int(block_size_bars))
    nblocks = -(-T // b)
    sess = np.repeat(rng.integers(0, S, size=(n, nblocks)), b, axis=1)[:, :T]
    slots = np.broadcast_to(_slots(k, last), (n, T))
    return pool[sess, slots]


def slot_sigma(pool, k, last):
    """Per-slot standard deviation of 5-minute log close returns across sessions."""
    lr = np.log(pool[:, k + 1:last + 1, 3])
    return lr.std(axis=0, ddof=1)


def gbm(pool, k, last, n, rng, sigma=None, **_):
    T = last - k
    sig = slot_sigma(pool, k, last) if sigma is None else np.broadcast_to(np.asarray(sigma, float), (T,))
    var = sig ** 2
    x = rng.standard_normal((n, T)) * sig - 0.5 * var          # log close-to-close, E[price] constant
    # Brownian bridge from 0 to x with variance var: exact marginal max / min
    u1 = 1.0 - rng.random((n, T))                               # (0, 1]
    u2 = 1.0 - rng.random((n, T))
    mx = 0.5 * (x + np.sqrt(x * x - 2.0 * var * np.log(u1)))
    mn = 0.5 * (x - np.sqrt(x * x - 2.0 * var * np.log(u2)))
    rel = np.empty((n, T, 4))
    rel[..., 0] = 1.0
    rel[..., 1] = np.exp(mx)
    rel[..., 2] = np.exp(mn)
    rel[..., 3] = np.exp(x)
    return rel


def regime_shock(pool, k, last, n, rng, block_size_bars=6, vol_multiplier=2.0, gap_prob=0.05,
                 gap_size_r=1.5, entry=None, risk=None, side="buy", **_):
    rel = block_bootstrap(pool, k, last, n, rng, block_size_bars=block_size_bars)
    # Scale only the deviation from each slot's mean log close return, so the pool's own
    # drift is kept as-is rather than amplified (a stress test must not add edge).
    # Affine with a positive slope: keeps l <= o,c <= h.
    mu = np.log(pool[:, k + 1:last + 1, 3]).mean(axis=0)[None, :, None]
    rel = np.exp(mu + (np.log(rel) - mu) * float(vol_multiplier))
    if gap_prob > 0 and entry and risk:
        T = rel.shape[1]
        hit = rng.random(n) < gap_prob
        at = rng.integers(0, T, size=n)
        sign = -1.0 if side == "buy" else 1.0                   # adverse for the position
        factor = 1.0 + sign * gap_size_r * risk / entry
        if factor <= 0:
            raise ValueError("gap_size_r too large for this price")
        idx = np.nonzero(hit)[0]
        rel[idx, at[idx], :] *= factor
    return rel


GENERATORS = {"bar_bootstrap": bar_bootstrap, "block_bootstrap": block_bootstrap,
              "gbm": gbm, "regime_shock": regime_shock}


def generate(model, pool, k, last, n, seed, **params):
    if model not in GENERATORS:
        raise ValueError("unknown model %r (known: %s)" % (model, ", ".join(MODELS)))
    return GENERATORS[model](pool, k, last, n, rng_for(seed, model), **params)
