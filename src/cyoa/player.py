"""Player-side logic: seeded weighted chance roll."""

from __future__ import annotations

import random


def roll(options: list[tuple[int, int]], rng: random.Random) -> int:
    """Return one target page id, drawn by weight from ``options``."""
    targets = [target for target, _weight in options]
    weights = [weight for _target, weight in options]
    return rng.choices(targets, weights=weights, k=1)[0]
