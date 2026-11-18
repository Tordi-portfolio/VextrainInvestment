# VextrainInvestment (crypto investment simulator)

A Django learning project. Users trade **virtual** crypto at real CoinGecko prices.
No real deposits, wallets or payouts exist, and none should be added.

## How balances work
- A user's balance is held in four coins: BTC, ETH, BNB and USDT.
- **Total balance = the value of all four coins added together.**
- Every new account gets a **20 USDT welcome bonus** (`WELCOME_BONUS_USDT` in `settings.py`).
- USDT is the base currency: Buy spends USDT, Sell returns USDT. Convert swaps any coin for any other.

## Setup
```bash
python -m venv venv && source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
python manage.py migrate
python manage.py seed_coins                          # BTC, ETH, BNB, USDT
python manage.py createsuperuser                     # your admin login
python manage.py runserver
```

## Pages
- `/` landing page with the market and the real count of active users (logged in within `ACTIVE_USER_DAYS`, 30 by default)
- `/signup/`, `/login/` then `/dashboard/` (total balance, assets, allocation, value chart)
- `/market/` list with 7-day sparklines; `/market/<SYMBOL>/` has a 1D/7D/30D price chart and Buy / Sell
- `/convert/` swap between any two of BTC, ETH, BNB and USDT at current prices
- `/withdraw/` simulated withdrawal by asset, blockchain network and wallet address (format-checked only)
  - Locked until the user's total balance reaches `WITHDRAWAL_MIN_TOTAL_USD` and the coin being withdrawn is worth at least `WITHDRAWAL_MIN_ASSET_USD` (both $700 by default)
- `/history/` the user's activity
- `/manage/` staff-only admin panel: see every user's BTC, ETH, BNB and USDT balances and total, set/add/subtract any coin balance for a user (reason required, audit-logged), reset accounts, add or hide coins
- `/manage/withdrawals/` complete a withdrawal request, or reject it and refund the coins
- `/manage/users/<id>/history/` full transaction history for one user (admin changes show the admin and the reason)
- `/django-admin/` the built-in Django admin

## Where things live
- `simulator/models.py` data model (Coin, Wallet, Holding, Transaction, Snapshot, AuditLog, Withdrawal)
- `simulator/logic.py` prices, charts, buy/sell/convert, withdrawals, admin balance tools
- `simulator/views.py` and `templates/` the pages (CSS is embedded in `templates/base.html`)
- `vextrain/settings.py` has the welcome bonus, withdrawal limits and cache times

Set `DJANGO_SECRET_KEY`, `DJANGO_DEBUG=0` and `DJANGO_ALLOWED_HOSTS` before hosting anywhere.
"# VextrainInvestment" 
