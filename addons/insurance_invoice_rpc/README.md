# Insurance Policy-first Invoice (POC) - Odoo 18

This build intentionally ships **NO XML files** to avoid strict RelaxNG validation errors on your server.

What it provides:
- Model: invoice.poc.payload
- Method: action_create_policy_and_invoice()
- Post-init hook creates a Mail Template and registers an XMLID.

You can run your payload via Odoo shell to test invoice creation end-to-end.
