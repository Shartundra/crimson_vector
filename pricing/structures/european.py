from pricing._registry import register
from pricing.models import black76 as _b76


@register("european", "black76")
def _price(F: float, K: float, T: float, r: float, sigma: float, call_put: str):
    return _b76.price(F=F, K=K, T=T, r=r, sigma=sigma, call_put=call_put)
