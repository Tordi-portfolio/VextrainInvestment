from django.contrib import admin

from .models import AuditLog, Coin, Holding, Snapshot, Transaction, Wallet

admin.site.register(Coin)
admin.site.register(Wallet)
admin.site.register(Holding)
admin.site.register(Snapshot)


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ("created_at", "user", "kind", "coin", "quantity", "usd")


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "admin", "target", "action", "coin", "old_qty", "new_qty")
    readonly_fields = [f.name for f in AuditLog._meta.fields]
