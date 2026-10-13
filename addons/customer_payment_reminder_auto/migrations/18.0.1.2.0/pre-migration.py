def migrate(cr, version):
    """Make the mail template updatable again.

    Odoo skips records whose ir_model_data row has ``noupdate = true`` when a
    module is upgraded, and that flag is never cleared by a data file. If the
    template was ever loaded as noupdate (or toggled in the UI), the corrected
    template shipped by the module would never reach the database. Clearing the
    flag here lets the data file update the template during this upgrade.
    The cron record is flagged noupdate so upgrades keep its active state.
    """
    cr.execute("""
        UPDATE ir_model_data
           SET noupdate = FALSE
         WHERE module = 'customer_payment_reminder_auto'
           AND name = 'mail_template_customer_payment_reminder'
    """)
    cr.execute("""
        UPDATE ir_model_data
           SET noupdate = TRUE
         WHERE module = 'customer_payment_reminder_auto'
           AND name = 'ir_cron_customer_payment_reminder'
    """)
