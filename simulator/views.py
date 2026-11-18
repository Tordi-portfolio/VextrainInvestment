from decimal import Decimal

from django import forms
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from . import logic
from .models import AuditLog, Coin, Snapshot, Transaction, Withdrawal
from .templatetags.vex import coin_color

staff_required = user_passes_test(lambda u: u.is_active and u.is_staff, login_url="login")


class SignupForm(UserCreationForm):
    email = forms.EmailField(required=True)

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "email")


class AmountForm(forms.Form):
    amount = forms.DecimalField(required=False, min_value=Decimal("0.00000001"), max_digits=24, decimal_places=8)
    sell_all = forms.BooleanField(required=False)


class AdjustForm(forms.Form):
    coin = forms.ModelChoiceField(Coin.objects.filter(is_active=True), to_field_name="symbol", label="Coin")
    mode = forms.ChoiceField(choices=[("set", "Set balance to"), ("add", "Add"), ("subtract", "Subtract")],
                             label="Action")
    amount = forms.DecimalField(min_value=Decimal("0"), max_digits=24, decimal_places=8,
                                label="Amount (in coin units, e.g. 0.05 BTC or 50 USDT)")
    note = forms.CharField(max_length=200, label="Reason (saved in the audit log)")


class CoinForm(forms.ModelForm):
    class Meta:
        model = Coin
        fields = ("symbol", "name", "coingecko_id", "is_active")


class ConvertForm(forms.Form):
    from_coin = forms.ModelChoiceField(Coin.objects.filter(is_active=True), to_field_name="symbol")
    to_coin = forms.ModelChoiceField(Coin.objects.filter(is_active=True), to_field_name="symbol")
    amount = forms.DecimalField(min_value=Decimal("0.00000001"), max_digits=24, decimal_places=8)


class WithdrawForm(forms.Form):
    coin = forms.ModelChoiceField(Coin.objects.filter(is_active=True), to_field_name="symbol")
    network = forms.ChoiceField(choices=[(k, v[0]) for k, v in logic.NETWORKS.items()])
    address = forms.CharField(max_length=120)
    amount = forms.DecimalField(min_value=Decimal("0.00000001"), max_digits=24, decimal_places=8)



def plan(request):
    amounts = [
        500, 700, 1000, 1500, 2000, 3000,
        5000, 10000, 20000, 50000, 100000
    ]

    assets = [
        {
            "name": "Bitcoin",
            "symbol": "BTC",
            "icon": "₿",
            "css": "btc-icon"
        },
        {
            "name": "Ethereum",
            "symbol": "ETH",
            "icon": "◆",
            "css": "eth-icon"
        },
        {
            "name": "Binance Coin",
            "symbol": "BNB",
            "icon": "◆",
            "css": "bnb-icon"
        },
        {
            "name": "USDT",
            "symbol": "USDT",
            "icon": "₮",
            "css": "usdt-icon"
        },
        # {
        #     "name": "Solana",
        #     "symbol": "SOL",
        #     "icon": "S",
        #     "css": "sol-icon"
        # },
        # {
        #     "name": "Polkadot",
        #     "symbol": "DOT",
        #     "icon": "D",
        #     "css": "dot-icon"
        # },
        # {
        #     "name": "Dogecoin",
        #     "symbol": "DOGE",
        #     "icon": "Ð",
        #     "css": "doge-icon"
        # },
    ]

    plans = []

    for asset in assets:
        asset_plans = []

        for amount in amounts:
            gain = amount * 0.50

            asset_plans.append({
                "amount": amount,
                "gain": gain,
                "total": amount + gain,
            })

        plans.append({
            **asset,
            "plans": asset_plans,
        })

    return render(request, "plan.html", {
        "plans": plans
    })



def _held(user):
    p = logic.portfolio(user)
    return p, {r["coin"].pk: r for r in p["rows"]}


# ---------- public ----------
def home(request):
    logic.refresh_prices()
    logic.refresh_charts()
    return render(request, "home.html", {"coins": Coin.objects.filter(is_active=True),
                                         "active_users": logic.active_user_count(),
                                         "active_days": settings.ACTIVE_USER_DAYS})


def signup(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    form = SignupForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user)
        messages.success(request, "Welcome! Your wallet starts with a 20 USDT welcome bonus to practise with.")
        return redirect("dashboard")
    return render(request, "signup.html", {"form": form})


# ---------- user area ----------
@login_required
def dashboard(request):
    logic.refresh_prices()
    logic.refresh_charts()
    logic.snapshot(request.user)
    p, held = _held(request.user)
    assets = [{"coin": c, "quantity": held[c.pk]["quantity"] if c.pk in held else Decimal("0"),
               "value": held[c.pk]["value"] if c.pk in held else Decimal("0")}
              for c in Coin.objects.filter(is_active=True)]
    alloc = [{"label": r["coin"].symbol, "value": r["value"], "color": coin_color(r["coin"].symbol),
              "pct": float(r["value"] / p["total"] * 100)}
             for r in p["rows"] if p["total"] > 0 and r["value"] > 0]
    points = list(Snapshot.objects.filter(user=request.user)[:100])[::-1]
    chart = {"labels": [timezone.localtime(s.created_at).strftime("%b %d %H:%M") for s in points],
             "values": [float(s.value) for s in points]}
    return render(request, "dashboard.html", {"p": p, "assets": assets, "alloc": alloc, "chart": chart})


@login_required
def market(request):
    live = logic.refresh_prices()
    logic.refresh_charts()
    return render(request, "market.html", {"coins": Coin.objects.filter(is_active=True), "live": live})


@login_required
def coin_detail(request, symbol):
    logic.refresh_prices()
    coin = get_object_or_404(Coin, symbol__iexact=symbol, is_active=True)
    logic.refresh_chart(coin)
    coin.refresh_from_db()
    p, held_map = _held(request.user)
    held = held_map.get(coin.pk)
    usdt = logic.usdt_coin()
    usdt_held = held_map.get(usdt.pk)
    usdt_balance = usdt_held["quantity"] if usdt_held else Decimal("0")
    data = {"chart": coin.chart, "symbol": coin.symbol, "price": float(coin.price_usd),
            "usdt": float(usdt_balance), "usdt_price": float(usdt.price_usd),
            "qty": float(held["quantity"]) if held else 0}
    return render(request, "coin.html", {"coin": coin, "held": held, "data": data,
                                         "usdt_balance": usdt_balance, "is_base": coin.pk == usdt.pk})


@login_required
@require_POST
def buy(request, symbol):
    coin = get_object_or_404(Coin, symbol__iexact=symbol, is_active=True)
    form = AmountForm(request.POST)
    try:
        if not form.is_valid() or not form.cleaned_data["amount"]:
            raise logic.TradeError("Enter a valid USD amount.")
        logic.refresh_prices()
        qty = logic.buy(request.user, coin, form.cleaned_data["amount"])
        messages.success(request, f"Bought {qty.normalize():f} {coin.symbol} with {form.cleaned_data['amount'].normalize():f} USDT.")
    except logic.TradeError as e:
        messages.error(request, str(e))
    return redirect("coin", symbol=coin.symbol)


@login_required
@require_POST
def sell(request, symbol):
    coin = get_object_or_404(Coin, symbol__iexact=symbol, is_active=True)
    form = AmountForm(request.POST)
    try:
        if not form.is_valid():
            raise logic.TradeError("Enter a valid quantity.")
        logic.refresh_prices()
        proceeds = logic.sell(request.user, coin, form.cleaned_data["amount"], form.cleaned_data["sell_all"])
        messages.success(request, f"Sold {coin.symbol} for {proceeds.normalize():f} USDT.")
    except logic.TradeError as e:
        messages.error(request, str(e))
    return redirect("coin", symbol=coin.symbol)


@login_required
def convert(request):
    logic.refresh_prices()
    if request.method == "POST":
        form = ConvertForm(request.POST)
        try:
            if not form.is_valid():
                raise logic.TradeError("Choose two coins and enter an amount to convert.")
            d = form.cleaned_data
            got = logic.convert(request.user, d["from_coin"], d["to_coin"], d["amount"])
            messages.success(request, f"Converted {d['amount'].normalize():f} {d['from_coin'].symbol} "
                                      f"to {got.normalize():f} {d['to_coin'].symbol}.")
        except logic.TradeError as e:
            messages.error(request, str(e))
        return redirect("convert")
    _, held = _held(request.user)
    assets = {c.symbol: {"name": c.name, "price": float(c.price_usd),
                         "balance": float(held[c.pk]["quantity"]) if c.pk in held else 0}
              for c in Coin.objects.filter(is_active=True)}
    return render(request, "convert.html", {"assets": assets})


@login_required
def withdraw(request):
    logic.refresh_prices()
    if request.method == "POST":
        form = WithdrawForm(request.POST)
        try:
            if not form.is_valid():
                raise logic.TradeError("Check the asset, network, address and amount, then try again.")
            d = form.cleaned_data
            w = logic.request_withdrawal(request.user, d["coin"], d["amount"], d["network"], d["address"])
            messages.success(request, f"Withdrawal of {w.amount.normalize():f} {w.coin.symbol} submitted. "
                                      "It stays pending until an admin processes it.")
            return redirect("withdraw")
        except logic.TradeError as e:
            messages.error(request, str(e))
            return redirect("withdraw")
    p, held = _held(request.user)
    minimum = settings.WITHDRAWAL_MIN_TOTAL_USD
    assets = {}
    for c in Coin.objects.filter(is_active=True, symbol__in=logic.ASSET_NETWORKS.keys()):
        assets[c.symbol] = {"name": c.name, "price": float(c.price_usd),
                            "balance": float(held[c.pk]["quantity"]) if c.pk in held else 0,
                            "networks": [[k, logic.NETWORKS[k][0]] for k in logic.ASSET_NETWORKS[c.symbol]]}
    return render(request, "withdraw.html", {
        "min_total": minimum, "min_asset": settings.WITHDRAWAL_MIN_ASSET_USD, "total": p["total"], "unlocked": p["total"] >= minimum,
        "remaining": max(minimum - p["total"], Decimal("0")),
        "progress": float(min(p["total"] / minimum * 100, 100)),
        "assets": assets, "withdrawals": Withdrawal.objects.filter(user=request.user).select_related("coin")[:20]})


@login_required
def history(request):
    page = Paginator(Transaction.objects.filter(user=request.user).select_related("coin"), 25)
    return render(request, "history.html", {"page": page.get_page(request.GET.get("page"))})


# ---------- admin dashboard (staff only) ----------
@staff_required
def manage_home(request):
    logic.refresh_prices()
    q = request.GET.get("q", "").strip()
    users = User.objects.order_by("-date_joined")
    if q:
        users = users.filter(username__icontains=q)
    page = Paginator(users, 20).get_page(request.GET.get("page"))
    portfolios = [(u, logic.portfolio(u)) for u in page]
    rows = [(u, p, {r["coin"].symbol: r["quantity"] for r in p["rows"]}) for u, p in portfolios]
    return render(request, "manage_home.html", {
        "page": page, "rows": rows, "q": q, "coins": Coin.objects.filter(is_active=True), "user_count": User.objects.count(),
        "pending": Withdrawal.objects.filter(status=Withdrawal.PENDING).count(),
        "active_users": logic.active_user_count(), "active_days": settings.ACTIVE_USER_DAYS,
        "audit": AuditLog.objects.select_related("admin", "target")[:10]})


@staff_required
def manage_user(request, user_id):
    target = get_object_or_404(User, pk=user_id)
    p = logic.portfolio(target)
    held = {r["coin"].pk: r for r in p["rows"]}
    balances = [{"coin": c, "quantity": held[c.pk]["quantity"] if c.pk in held else Decimal("0"),
                 "value": held[c.pk]["value"] if c.pk in held else Decimal("0")}
                for c in Coin.objects.filter(is_active=True)]
    return render(request, "manage_user.html", {
        "target": target, "p": p, "balances": balances, "form": AdjustForm(),
        "txns": Transaction.objects.filter(user=target).select_related("coin")[:15],
        "audit": AuditLog.objects.filter(target=target).select_related("admin")[:10]})


@staff_required
def manage_user_history(request, user_id):
    target = get_object_or_404(User, pk=user_id)
    page = Paginator(Transaction.objects.filter(user=target).select_related("coin", "created_by"), 25)
    return render(request, "manage_history.html", {"target": target, "page": page.get_page(request.GET.get("page"))})


@staff_required
@require_POST
def manage_adjust(request, user_id):
    target = get_object_or_404(User, pk=user_id)
    form = AdjustForm(request.POST)
    if form.is_valid():
        try:
            logic.admin_adjust_balance(request.user, target, **form.cleaned_data)
            messages.success(request, f"Updated {target.username}'s {form.cleaned_data['coin'].symbol} balance.")
        except logic.TradeError as e:
            messages.error(request, str(e))
    else:
        messages.error(request, "Check the coin, amount and reason, then try again.")
    return redirect("manage_user", user_id=target.pk)


@staff_required
@require_POST
def manage_reset(request, user_id):
    target = get_object_or_404(User, pk=user_id)
    logic.admin_reset_user(request.user, target)
    messages.success(request, f"{target.username}'s account was reset.")
    return redirect("manage_user", user_id=target.pk)


@staff_required
def manage_withdrawals(request):
    qs = Withdrawal.objects.select_related("user", "coin", "processed_by")
    return render(request, "manage_withdrawals.html", {
        "pending": qs.filter(status=Withdrawal.PENDING),
        "done": qs.exclude(status=Withdrawal.PENDING)[:50]})


@staff_required
@require_POST
def manage_withdrawal_process(request, withdrawal_id):
    w = get_object_or_404(Withdrawal, pk=withdrawal_id)
    approve = request.POST.get("action") == "approve"
    try:
        logic.process_withdrawal(request.user, w, approve, request.POST.get("note", "").strip()[:200])
        messages.success(request, "Withdrawal completed." if approve else "Withdrawal rejected and coins returned.")
    except logic.TradeError as e:
        messages.error(request, str(e))
    return redirect("manage_withdrawals")


@staff_required
def manage_coins(request):
    form = CoinForm(request.POST or None)
    if request.method == "POST":
        if "refresh" in request.POST:
            ok = logic.refresh_prices(force=True)
            for c in Coin.objects.filter(is_active=True):
                logic.refresh_chart(c, force=True)
            (messages.success if ok else messages.error)(
                request, "Prices refreshed." if ok else "Couldn't reach CoinGecko. Try again shortly.")
            return redirect("manage_coins")
        if form.is_valid():
            form.save()
            logic.refresh_prices(force=True)
            messages.success(request, "Coin added.")
            return redirect("manage_coins")
    return render(request, "manage_coins.html", {"coins": Coin.objects.all(), "form": form})


@staff_required
@require_POST
def manage_coin_toggle(request, coin_id):
    coin = get_object_or_404(Coin, pk=coin_id)
    coin.is_active = not coin.is_active
    coin.save(update_fields=["is_active"])
    return redirect("manage_coins")
