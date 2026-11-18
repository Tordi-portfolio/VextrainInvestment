from decimal import Decimal

from django.core.management.base import BaseCommand

from simulator.logic import refresh_charts, refresh_prices
from simulator.models import Coin

COINS = [  # symbol, name, coingecko id, fallback price used until live prices load
    ("BTC", "Bitcoin", "bitcoin", "65000"),
    ("ETH", "Ethereum", "ethereum", "3200"),
    ("BNB", "BNB", "binancecoin", "580"),
    ("USDT", "Tether", "tether", "1"),
]


class Command(BaseCommand):
    help = "Create the four supported coins (BTC, ETH, BNB, USDT) and try to fetch live prices and charts."

    def handle(self, *args, **options):
        for symbol, name, cg_id, fallback in COINS:
            Coin.objects.get_or_create(symbol=symbol, defaults={
                "name": name, "coingecko_id": cg_id, "price_usd": Decimal(fallback)})
        Coin.objects.exclude(symbol__in=[c[0] for c in COINS]).update(is_active=False)
        live = refresh_prices(force=True)
        refresh_charts()
        self.stdout.write(self.style.SUCCESS(
            "Coins ready. " + ("Live prices loaded." if live else "Offline: using reference prices.")))
