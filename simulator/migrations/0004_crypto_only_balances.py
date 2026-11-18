from decimal import ROUND_DOWN, Decimal

import django.db.models.deletion
from django.db import migrations, models


def _usdt(apps):
    Coin = apps.get_model("simulator", "Coin")
    return Coin.objects.get_or_create(symbol="USDT", defaults={
        "name": "Tether", "coingecko_id": "tether", "price_usd": Decimal("1")})[0]


def cash_to_usdt(apps, schema_editor):
    """Existing users' USD cash becomes USDT, so nothing they had is lost."""
    Wallet, Holding = apps.get_model("simulator", "Wallet"), apps.get_model("simulator", "Holding")
    for wallet in Wallet.objects.filter(cash__gt=0):
        coin = _usdt(apps)
        price = coin.price_usd if coin.price_usd > 0 else Decimal("1")
        holding, _ = Holding.objects.get_or_create(user_id=wallet.user_id, coin=coin)
        holding.quantity += (wallet.cash / price).quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)
        holding.cost_basis += wallet.cash
        holding.save()
        wallet.cash = 0
        wallet.save(update_fields=["cash"])


def label_old_audit_rows(apps, schema_editor):
    """Old audit rows recorded cash amounts; show them as USDT."""
    AuditLog = apps.get_model("simulator", "AuditLog")
    if AuditLog.objects.exists():
        AuditLog.objects.filter(coin__isnull=True).update(coin=_usdt(apps))


class Migration(migrations.Migration):

    dependencies = [("simulator", "0003_alter_transaction_kind")]

    operations = [
        migrations.RunPython(cash_to_usdt, migrations.RunPython.noop),
        migrations.RenameField("auditlog", "old_cash", "old_qty"),
        migrations.RenameField("auditlog", "new_cash", "new_qty"),
        migrations.AlterField("auditlog", "old_qty", models.DecimalField(
            blank=True, null=True, max_digits=24, decimal_places=8)),
        migrations.AlterField("auditlog", "new_qty", models.DecimalField(
            blank=True, null=True, max_digits=24, decimal_places=8)),
        migrations.AddField("auditlog", "coin", models.ForeignKey(
            blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
            related_name="+", to="simulator.coin")),
        migrations.RunPython(label_old_audit_rows, migrations.RunPython.noop),
        migrations.RemoveField("wallet", "cash"),
        migrations.AlterField("wallet", "baseline", models.DecimalField(
            decimal_places=2, default=0, max_digits=16)),
    ]
