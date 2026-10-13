def migrate(cr, version):
    """Cooldown between reminders is 8 days (was configured as 10)."""
    cr.execute("""
        UPDATE res_company
           SET payment_reminder_cooldown_days = 8
         WHERE payment_reminder_cooldown_days = 10
    """)
