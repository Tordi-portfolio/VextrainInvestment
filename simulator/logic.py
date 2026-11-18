"""Prices, charts, wallet maths, trading, withdrawals and admin balance tools.

A user's whole balance is held in four coins (BTC, ETH, BNB, USDT). USDT is the base currency:
"buy" spends USDT and "sell" returns USDT. Total balance = value of all coins added together.
"""
import json
import re
import urllib.parse
import urllib.request
from datetime import timedelta
from decimal import ROUND_DOWN, Decimal

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import WELCOME_NOTE, AuditLog, Coin, Holding, Snapshot, Transaction, Wallet, Withdrawal

CENT = Decimal("0.01")
UNIT = Decimal("0.00000001")
_last_failure = None
_chart_failure = None


class TradeError(Exception):
    """Raised with a message that is safe to show to the user."""


# ---------- wallet and welcome bonus ----------
def usdt_coin():
    return Coin.objects.get_or_create(symbol="USDT", defaults={
        "name": "Tether", "coingecko_id": "tether", "price_usd": Decimal("1")})[0]


def _grant_welcome_bonus(wallet):
    coin = usdt_coin()
    qty = settings.WELCOME_BONUS_USDT
    value = (qty * coin.price_usd).quantize(CENT)
    holding, _ = Holding.objects.get_or_create(user=wallet.user, coin=coin)
    holding.quantity += qty
    holding.cost_basis += value
    holding.save()
    wallet.baseline += value
    wallet.save(update_fields=["baseline"])
    Transaction.objects.create(user=wallet.user, kind=Transaction.ADJUST, coin=coin, quantity=qty,
                               price=coin.price_usd, note=WELCOME_NOTE)


def get_wallet(user):
    wallet, created = Wallet.objects.get_or_create(user=user)
    if created:
        _grant_welcome_bonus(wallet)
    return wallet


# ---------- prices ----------
def refresh_prices(force=False):
    """Fetch USD prices from CoinGecko (cached). Returns False if the API was unreachable."""
    global _last_failure
    now = timezone.now()
    if not force and _last_failure and (now - _last_failure).total_seconds() < 60:
        return False
    coins = list(Coin.objects.filter(is_active=True))
    cutoff = now - timedelta(seconds=settings.PRICE_CACHE_SECONDS)
    if not coins or (not force and all(c.price_updated_at and c.price_updated_at > cutoff for c in coins)):
        return True
    query = urllib.parse.urlencode({
        "ids": ",".join({c.coingecko_id for c in coins}),
        "vs_currencies": "usd",
        "include_24hr_change": "true",
    })
    request = urllib.request.Request(
        "https://api.coingecko.com/api/v3/simple/price?" + query, headers={"User-Agent": "vextrain-sim"}
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            data = json.load(response)
    except Exception:
        _last_failure = now
        return False
    for coin in coins:
        row = data.get(coin.coingecko_id)
        if row and "usd" in row:
            coin.price_usd = Decimal(str(row["usd"]))
            coin.change_24h = Decimal(str(row.get("usd_24h_change") or 0)).quantize(CENT)
            coin.price_updated_at = now
            coin.save(update_fields=["price_usd", "change_24h", "price_updated_at"])
    return True


def refresh_chart(coin, force=False):
    """Store ~30 days of hourly prices on the coin (cached). Returns True if chart data is usable."""
    global _chart_failure
    now = timezone.now()
    fresh = coin.chart_updated_at and (now - coin.chart_updated_at).total_seconds() < settings.CHART_CACHE_SECONDS
    if fresh and not force:
        return bool(coin.chart)
    if _chart_failure and (now - _chart_failure).total_seconds() < 60 and not force:
        return bool(coin.chart)
    url = (f"https://api.coingecko.com/api/v3/coins/{urllib.parse.quote(coin.coingecko_id)}"
           "/market_chart?vs_currency=usd&days=30")
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "vextrain-sim"}), timeout=5) as r:
            prices = json.load(r)["prices"]
    except Exception:
        _chart_failure = now
        return bool(coin.chart)
    coin.chart = [[int(t), round(p, 8)] for t, p in prices]
    coin.chart_updated_at = now
    coin.save(update_fields=["chart", "chart_updated_at"])
    return True


def refresh_charts():
    for coin in Coin.objects.filter(is_active=True):
        refresh_chart(coin)


# ---------- portfolio ----------
def portfolio(user):
    """Total balance is every coin's value added together."""
    wallet = get_wallet(user)
    rows, total = [], Decimal("0")
    for h in Holding.objects.filter(user=user, quantity__gt=0).select_related("coin").order_by("coin__symbol"):
        value = (h.quantity * h.coin.price_usd).quantize(CENT)
        rows.append({"coin": h.coin, "quantity": h.quantity, "cost": h.cost_basis,
                     "value": value, "pl": value - h.cost_basis})
        total += value
    return {"wallet": wallet, "rows": rows, "total": total, "pl": total - wallet.baseline}


def snapshot(user, force=False):
    last = Snapshot.objects.filter(user=user).first()
    if not force and last and timezone.now() - last.created_at < timedelta(minutes=10):
        return
    Snapshot.objects.create(user=user, value=portfolio(user)["total"])


# ---------- trading and converting ----------
def convert(user, from_coin, to_coin, quantity, kind=Transaction.CONVERT, out_note=None, in_note=None):
    """Swap one coin for another at current prices. Cost basis moves with the value."""
    if from_coin.pk == to_coin.pk:
        raise TradeError("Choose two different coins.")
    qty = Decimal(quantity).quantize(UNIT, rounding=ROUND_DOWN)
    if qty <= 0:
        raise TradeError("Enter an amount greater than zero.")
    with transaction.atomic():
        src = Coin.objects.get(pk=from_coin.pk, is_active=True)
        dst = Coin.objects.get(pk=to_coin.pk, is_active=True)
        if src.price_usd <= 0 or dst.price_usd <= 0:
            raise TradeError("Prices aren't available yet. Try again shortly.")
        holding = Holding.objects.select_for_update().filter(user=user, coin=src).first()
        if not holding or qty > holding.quantity:
            raise TradeError(f"You don't have that much {src.symbol}.")
        to_qty = (qty * src.price_usd / dst.price_usd).quantize(UNIT, rounding=ROUND_DOWN)
        if to_qty <= 0:
            raise TradeError("That amount is too small.")
        if qty == holding.quantity:
            cost = holding.cost_basis
            holding.delete()
        else:
            cost = (holding.cost_basis * qty / holding.quantity).quantize(CENT)
            holding.cost_basis -= cost
            holding.quantity -= qty
            holding.save()
        target, _ = Holding.objects.select_for_update().get_or_create(user=user, coin=dst)
        target.quantity += to_qty
        target.cost_basis += cost
        target.save()
        Transaction.objects.create(user=user, kind=kind, coin=src, quantity=qty, price=src.price_usd,
                                   note=out_note or f"Converted to {dst.symbol}")
        Transaction.objects.create(user=user, kind=kind, coin=dst, quantity=to_qty, price=dst.price_usd,
                                   note=in_note or f"Received from {src.symbol}")
    snapshot(user, force=True)
    return to_qty


def buy(user, coin, usdt_amount):
    """Spend USDT to buy a coin. Returns the quantity bought."""
    usdt = usdt_coin()
    if coin.pk == usdt.pk:
        raise TradeError("USDT is your base currency. Use Convert to swap it for another coin.")
    return convert(user, usdt, coin, usdt_amount, Transaction.BUY, f"Paid for {coin.symbol}", "Bought with USDT")


def sell(user, coin, quantity=None, sell_all=False):
    """Sell a coin for USDT. Returns the USDT received."""
    usdt = usdt_coin()
    if coin.pk == usdt.pk:
        raise TradeError("USDT is your base currency. Use Convert to swap it for another coin.")
    if sell_all:
        holding = Holding.objects.filter(user=user, coin=coin).first()
        if not holding or holding.quantity <= 0:
            raise TradeError(f"You don't hold any {coin.symbol}.")
        quantity = holding.quantity
    return convert(user, coin, usdt, quantity or 0, Transaction.SELL,
                   f"Sold for USDT", f"Received from selling {coin.symbol}")


# ---------- simulated withdrawals ----------
_EVM = r"^0x[a-fA-F0-9]{40}$"
NETWORKS = {  # key: (label, address format)
    "bitcoin": ("Bitcoin", r"^(bc1[a-z0-9]{25,60}|[13][a-km-zA-HJ-NP-Z1-9]{25,34})$"),
    "ethereum": ("Ethereum (ERC-20)", _EVM),
    "bsc": ("BNB Smart Chain (BEP-20)", _EVM),
    "tron": ("Tron (TRC-20)", r"^T[a-km-zA-HJ-NP-Z1-9]{33}$"),
}
ASSET_NETWORKS = {"BTC": ["bitcoin"], "ETH": ["ethereum"], "BNB": ["bsc"], "USDT": ["ethereum", "bsc", "tron"]}


def request_withdrawal(user, coin, quantity, network, address):
    """Move coins out of the wallet into a pending withdrawal. Format-checks the address only."""
    minimum = settings.WITHDRAWAL_MIN_TOTAL_USD
    total = portfolio(user)["total"]
    if total < minimum:
        raise TradeError(f"Withdrawals unlock when your total balance reaches ${minimum:,.2f}. "
                         f"Yours is ${total:,.2f}.")
    address = address.strip()
    if network not in ASSET_NETWORKS.get(coin.symbol, []):
        raise TradeError(f"{coin.symbol} can't be withdrawn on that network.")
    if not re.match(NETWORKS[network][1], address):
        raise TradeError(f"That doesn't look like a valid {NETWORKS[network][0]} address.")
    qty = Decimal(quantity).quantize(UNIT, rounding=ROUND_DOWN)
    if qty <= 0:
        raise TradeError("Enter an amount to withdraw.")
    with transaction.atomic():
        coin = Coin.objects.get(pk=coin.pk)
        holding = Holding.objects.select_for_update().filter(user=user, coin=coin).first()
        if not holding or qty > holding.quantity:
            raise TradeError(f"You don't have that much {coin.symbol} available.")
        asset_min = settings.WITHDRAWAL_MIN_ASSET_USD
        asset_value = (holding.quantity * coin.price_usd).quantize(CENT)
        if asset_value < asset_min:
            raise TradeError(f"To withdraw {coin.symbol} you need at least ${asset_min:,.2f} worth of it. "
                             f"You hold ${asset_value:,.2f}. You can buy or convert more.")
        usd_value = (qty * coin.price_usd).quantize(CENT)
        if qty == holding.quantity:
            cost_removed = holding.cost_basis
            holding.delete()
        else:
            cost_removed = (holding.cost_basis * qty / holding.quantity).quantize(CENT)
            holding.cost_basis -= cost_removed
            holding.quantity -= qty
            holding.save()
        wallet = Wallet.objects.select_for_update().get(user=user)
        wallet.baseline -= usd_value   # value left the wallet, so it isn't a trading loss
        wallet.save(update_fields=["baseline"])
        w = Withdrawal.objects.create(user=user, coin=coin, amount=qty, network=network, address=address,
                                      usd_value=usd_value, cost_removed=cost_removed)
        Transaction.objects.create(user=user, kind=Transaction.WITHDRAW, coin=coin, quantity=qty,
                                   price=coin.price_usd, note=f"Requested on {NETWORKS[network][0]} to ...{address[-6:]}")
    snapshot(user, force=True)
    return w


def process_withdrawal(admin, withdrawal, approve, note=""):
    """Admin completes the request, or rejects it and returns the coins to the user."""
    with transaction.atomic():
        w = Withdrawal.objects.select_for_update().get(pk=withdrawal.pk)
        if w.status != Withdrawal.PENDING:
            raise TradeError("This withdrawal was already processed.")
        if approve:
            w.status = Withdrawal.COMPLETED
            Transaction.objects.create(user=w.user, kind=Transaction.WITHDRAW, coin=w.coin, price=w.coin.price_usd,
                                       created_by=admin,
                                       note="Withdrawal completed (simulated)" + (f": {note}" if note else ""))
        else:
            w.status = Withdrawal.REJECTED
            holding, _ = Holding.objects.select_for_update().get_or_create(user=w.user, coin=w.coin)
            holding.quantity += w.amount
            holding.cost_basis += w.cost_removed
            holding.save()
            get_wallet(w.user)
            wallet = Wallet.objects.select_for_update().get(user=w.user)
            wallet.baseline += w.usd_value
            wallet.save(update_fields=["baseline"])
            Transaction.objects.create(user=w.user, kind=Transaction.REFUND, coin=w.coin, quantity=w.amount,
                                       price=w.coin.price_usd, created_by=admin,
                                       note="Withdrawal rejected" + (f": {note}" if note else ""))
        w.admin_note, w.processed_by, w.processed_at = note, admin, timezone.now()
        w.save()
    snapshot(w.user, force=True)
    return w


# ---------- admin tools ----------
def admin_adjust_balance(admin, target, coin, mode, amount, note):
    """Set, add to or subtract from one of a user's coin balances (amount is in coin units)."""
    amount = Decimal(amount).quantize(UNIT, rounding=ROUND_DOWN)
    with transaction.atomic():
        coin = Coin.objects.get(pk=coin.pk)
        get_wallet(target)
        wallet = Wallet.objects.select_for_update().get(user=target)
        holding, _ = Holding.objects.select_for_update().get_or_create(user=target, coin=coin)
        old = holding.quantity
        new = {"set": amount, "add": old + amount, "subtract": old - amount}[mode]
        if new < 0:
            raise TradeError(f"{coin.symbol} balance can't go below zero.")
        delta = new - old
        value = (delta * coin.price_usd).quantize(CENT)
        if delta > 0:
            holding.cost_basis += value
        elif delta < 0:
            holding.cost_basis -= (holding.cost_basis * (-delta) / old).quantize(CENT)
        holding.quantity = new
        if new == 0:
            holding.delete()
        else:
            holding.save()
        wallet.baseline += value   # keeps profit/loss about trading, not admin edits
        wallet.save(update_fields=["baseline"])
        Transaction.objects.create(user=target, kind=Transaction.ADJUST, coin=coin, quantity=delta,
                                   price=coin.price_usd, note=note, created_by=admin)
        AuditLog.objects.create(admin=admin, target=target, action=f"{mode} {coin.symbol}", coin=coin,
                                old_qty=old, new_qty=new, note=note)
    snapshot(target, force=True)


def admin_reset_user(admin, target, note="Reset to welcome bonus"):
    with transaction.atomic():
        get_wallet(target)
        wallet = Wallet.objects.select_for_update().get(user=target)
        Holding.objects.filter(user=target).delete()
        Snapshot.objects.filter(user=target).delete()
        wallet.baseline = Decimal("0")
        wallet.save(update_fields=["baseline"])
        Transaction.objects.create(user=target, kind=Transaction.RESET, note=note, created_by=admin)
        AuditLog.objects.create(admin=admin, target=target, action="reset account", note=note)
        _grant_welcome_bonus(wallet)
    snapshot(target, force=True)


def active_user_count():
    """Real number of accounts that logged in within ACTIVE_USER_DAYS."""
    from django.contrib.auth.models import User
    since = timezone.now() - timedelta(days=settings.ACTIVE_USER_DAYS)
    return User.objects.filter(is_active=True, last_login__gte=since).count()
