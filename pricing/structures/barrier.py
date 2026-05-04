from pricing._registry import register
from pricing.models import reiner_rubinstein as _rr


@register("barrier", "reiner_rubinstein")
def _price(
    F: float,
    K: float,
    T: float,
    r: float,
    sigma: float,
    H: float,
    call_put: str,
    barrier_dir: str,
    knock: str,
    rebate: float = 0.0,
):
    return _rr.price(
        F=F, K=K, T=T, r=r, sigma=sigma,
        H=H, call_put=call_put, barrier_dir=barrier_dir,
        knock=knock, rebate=rebate,
    )
