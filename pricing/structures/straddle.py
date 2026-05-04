from pricing._registry import register_composite


@register_composite("straddle")
def _legs(F: float, K: float, T: float, r: float, sigma: float):
    """Long call + long put at the same strike. Works with any model that prices European."""
    return [
        (+1, "european", dict(call_put="call")),
        (+1, "european", dict(call_put="put")),
    ]
