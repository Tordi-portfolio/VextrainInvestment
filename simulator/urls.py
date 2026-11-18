from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("signup/", views.signup, name="signup"),
    path("login/", auth_views.LoginView.as_view(), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("market/", views.market, name="market"),
    path("market/<str:symbol>/", views.coin_detail, name="coin"),
    path("market/<str:symbol>/buy/", views.buy, name="buy"),
    path("market/<str:symbol>/sell/", views.sell, name="sell"),
    path("convert/", views.convert, name="convert"),
    path("withdraw/", views.withdraw, name="withdraw"),
    path("history/", views.history, name="history"),
    path("manage/", views.manage_home, name="manage_home"),
    path("manage/users/<int:user_id>/", views.manage_user, name="manage_user"),
    path("manage/users/<int:user_id>/history/", views.manage_user_history, name="manage_user_history"),
    path("manage/users/<int:user_id>/adjust/", views.manage_adjust, name="manage_adjust"),
    path("manage/users/<int:user_id>/reset/", views.manage_reset, name="manage_reset"),
    path("manage/withdrawals/", views.manage_withdrawals, name="manage_withdrawals"),
    path("manage/withdrawals/<int:withdrawal_id>/process/", views.manage_withdrawal_process, name="manage_withdrawal_process"),
    path("manage/coins/", views.manage_coins, name="manage_coins"),
    path("manage/coins/<int:coin_id>/toggle/", views.manage_coin_toggle, name="manage_coin_toggle"),

    path("plan/", views.plan, name="plan"),
]
