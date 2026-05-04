"""
Central dispatch for option pricing.

Primitives are registered via @register(structure, model).
Composites (wrappers built from legs) are registered via @register_composite(structure).
A composite automatically works with any model that can price its constituent legs —
no per-model registration needed.
"""
from __future__ import annotations

import inspect
from functools import lru_cache
from typing import Callable

from pricing._types import GreeksResult

# (structure, model) -> pricing function
_REGISTRY: dict[tuple[str, str], Callable[..., GreeksResult]] = {}

# structure -> legs function  (returns list of (sign, structure, params_dict))
_COMPOSITES: dict[str, Callable[..., list]] = {}


def register(structure: str, model: str):
    """Decorator: register a pricing function for a primitive structure + model pair."""
    def decorator(fn: Callable[..., GreeksResult]) -> Callable[..., GreeksResult]:
        _REGISTRY[(structure, model)] = fn
        return fn
    return decorator


def register_composite(structure: str):
    """Decorator: register a legs function for a composite structure.
    The composite is automatically priceable with any model that can price its legs.
    """
    def decorator(fn: Callable[..., list]) -> Callable[..., list]:
        _COMPOSITES[structure] = fn
        return fn
    return decorator


@lru_cache(maxsize=None)
def _accepted_params(fn: Callable) -> frozenset[str]:
    """Cache the set of parameter names a function accepts."""
    return frozenset(inspect.signature(fn).parameters)


def price(structure: str, model: str, **params) -> GreeksResult:
    """
    Price an option by structure and model.

    Parameters are forwarded to the registered pricing function; any extra keys
    not in its signature are silently filtered (allows uniform DataFrame rows
    to price mixed structures without manual column selection).

    Raises ValueError for unknown structure/model combinations.
    """
    if structure in _COMPOSITES:
        return _price_composite(structure, model, **params)

    key = (structure, model)
    if key not in _REGISTRY:
        valid_models = sorted(k[1] for k in _REGISTRY if k[0] == structure)
        if valid_models:
            raise ValueError(
                f"Model {model!r} not registered for structure {structure!r}. "
                f"Available models: {valid_models}"
            )
        known = sorted(k[0] for k in _REGISTRY) + sorted(_COMPOSITES)
        raise ValueError(
            f"Unknown structure {structure!r}. "
            f"Known structures: {sorted(set(known))}"
        )

    fn = _REGISTRY[key]
    accepted = _accepted_params(fn)
    return fn(**{k: v for k, v in params.items() if k in accepted})


def _price_composite(structure: str, model: str, **params) -> GreeksResult:
    legs_fn = _COMPOSITES[structure]
    accepted = _accepted_params(legs_fn)
    legs = legs_fn(**{k: v for k, v in params.items() if k in accepted})

    totals = [0.0] * len(GreeksResult._fields)
    for sign, leg_structure, leg_params in legs:
        # leg_params override outer params (e.g. call_put set per-leg)
        result = price(leg_structure, model, **{**params, **leg_params})
        for i, v in enumerate(result):
            totals[i] += sign * v
    return GreeksResult(*totals)
