from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver


def demo_balance():
    """Legacy default kept only so the first migration can still be imported."""
    return Decimal("0.00")


WELCOME_NOTE = "Welcome bonus"


class Coin(models.Model):
    symbol = models.CharField(max_length=10, unique=True)
    name = models.CharField(max_length=60)
    coingecko_id = models.CharField(max_length=80, help_text="ID used by the CoinGecko API, e.g. bitcoin")
    price_usd = models.DecimalField(max_digits=24, decimal_places=10, default=0)
    change_24h = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    price_updated_at = models.DateTimeField(null=True, blank=True)
    chart = models.JSONField(default=list, blank=True)  # [[ms timestamp, usd price], ...] for 30 days
    chart_updated_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["symbol"]

    def __str__(self):
        return self.symbol


class Wallet(models.Model):
    """One per user. The balance itself lives in Holding rows (BTC, ETH, BNB, USDT).
    `baseline` is the USD value the user has been given or withdrawn, so profit/loss reflects trading only."""
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="wallet")
    baseline = models.DecimalField(max_digits=16, decimal_places=2, default=0)

    def __str__(self):
        return f"{self.user} wallet"


class Holding(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="holdings")
    coin = models.ForeignKey(Coin, on_delete=models.CASCADE)
    quantity = models.DecimalField(max_digits=24, decimal_places=8, default=0)
    cost_basis = models.DecimalField(max_digits=16, decimal_places=2, default=0)

    class Meta:
        unique_together = ("user", "coin")


class Transaction(models.Model):
    BUY, SELL, ADJUST, RESET, WITHDRAW, REFUND, CONVERT = (
        "BUY", "SELL", "ADJUST", "RESET", "WITHDRAW", "REFUND", "CONVERT")
    KINDS = [(BUY, "Buy"), (SELL, "Sell"), (ADJUST, "Admin adjustment"), (RESET, "Account reset"),
             (WITHDRAW, "Withdrawal (simulated)"), (REFUND, "Withdrawal refund"), (CONVERT, "Convert")]
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="transactions")
    kind = models.CharField(max_length=10, choices=KINDS)
    coin = models.ForeignKey(Coin, null=True, blank=True, on_delete=models.SET_NULL)
    quantity = models.DecimalField(max_digits=24, decimal_places=8, default=0)
    price = models.DecimalField(max_digits=24, decimal_places=10, default=0)
    usd = models.DecimalField(max_digits=16, decimal_places=2, default=0)  # legacy, no longer used
    note = models.CharField(max_length=200, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="+")  # the admin, for admin changes
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    @property
    def label(self):
        if self.kind == self.ADJUST:
            if self.note == WELCOME_NOTE:
                return "Welcome bonus"
            return "Admin credit" if self.quantity >= 0 else "Admin debit"
        return self.get_kind_display()

    @property
    def value_usd(self):
        return (self.quantity * self.price).quantize(Decimal("0.01"))


class Snapshot(models.Model):
    """Total portfolio value at a point in time, for the history chart."""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="snapshots")
    value = models.DecimalField(max_digits=16, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]


class AuditLog(models.Model):
    """Every admin change to a user's balance is recorded here."""
    admin = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    target = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="audit_entries")
    action = models.CharField(max_length=60)
    coin = models.ForeignKey(Coin, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    old_qty = models.DecimalField(max_digits=24, decimal_places=8, null=True, blank=True)
    new_qty = models.DecimalField(max_digits=24, decimal_places=8, null=True, blank=True)
    note = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]


class Withdrawal(models.Model):
    """A simulated withdrawal request. Nothing is ever sent on a real blockchain."""
    PENDING, COMPLETED, REJECTED = "PENDING", "COMPLETED", "REJECTED"
    STATUSES = [(PENDING, "Pending"), (COMPLETED, "Completed"), (REJECTED, "Rejected")]
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="withdrawals")
    coin = models.ForeignKey(Coin, on_delete=models.PROTECT)
    amount = models.DecimalField(max_digits=24, decimal_places=8)
    network = models.CharField(max_length=20)
    address = models.CharField(max_length=120)
    usd_value = models.DecimalField(max_digits=16, decimal_places=2)
    cost_removed = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    status = models.CharField(max_length=10, choices=STATUSES, default=PENDING)
    admin_note = models.CharField(max_length=200, blank=True)
    processed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                     on_delete=models.SET_NULL, related_name="+")
    processed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    @property
    def network_label(self):
        from .logic import NETWORKS
        return NETWORKS.get(self.network, (self.network,))[0]


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_wallet(sender, instance, created, **kwargs):
    if created:
        from .logic import get_wallet  # creates the wallet and grants the welcome bonus
        get_wallet(instance)
