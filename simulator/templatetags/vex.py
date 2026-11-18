from decimal import Decimal

from django import template

register = template.Library()


def _d(value):
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal("0")


@register.filter
def money(value):
    d = _d(value).quantize(Decimal("0.01"))
    return f"{'-' if d < 0 else ''}${abs(d):,.2f}"


@register.filter
def price(value):
    d = _d(value)
    if d >= 1:
        return f"${d:,.2f}"
    if d >= Decimal("0.01"):
        return f"${d:,.4f}"
    return f"${d:,.8f}"


@register.filter
def qty(value):
    return f"{_d(value):.8f}".rstrip("0").rstrip(".") or "0"


@register.filter
def pct(value):
    d = _d(value)
    return f"{'+' if d > 0 else ''}{d:.2f}%"


@register.filter
def tone(value):
    d = _d(value)
    return "gain" if d > 0 else "loss" if d < 0 else "flat"


from django.utils.safestring import mark_safe  # noqa: E402

COIN_COLORS = {"BTC": "#F7931A", "ETH": "#627EEA", "BNB": "#D9A21B", "USDT": "#26A17B"}


@register.filter
def coin_color(symbol):
    return COIN_COLORS.get(str(symbol).upper(), "#5A6A8A")


@register.filter
def sparkline(coin):
    """Tiny inline SVG trend line from the coin's stored 7-day prices."""
    pts = [p[1] for p in (coin.chart or [])][-168:]
    if len(pts) < 2:
        return ""
    pts = pts[::max(1, len(pts) // 40)]
    lo, hi = min(pts), max(pts)
    flat = (hi - lo) / hi < 0.002 if hi else True
    w, h = 100, 32
    coords = " ".join(
        f"{i * w / (len(pts) - 1):.1f},{(h / 2 if flat else h - 2 - (p - lo) / (hi - lo) * (h - 4)):.1f}"
        for i, p in enumerate(pts))
    color = "#2EC27E" if pts[-1] >= pts[0] else "#F0616D"
    return mark_safe(f'<svg viewBox="0 0 {w} {h}" width="100" height="32" preserveAspectRatio="none" '
                     f'aria-hidden="true"><polyline fill="none" stroke="{color}" stroke-width="1.6" '
                     f'stroke-linejoin="round" points="{coords}"/></svg>')


@register.filter
def get(mapping, key):
    """Look up a dict value in a template: {{ balances|get:coin.symbol }}."""
    return mapping.get(key, 0)
