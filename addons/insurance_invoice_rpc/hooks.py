# -*- coding: utf-8 -*-
from odoo import api, SUPERUSER_ID

MODULE = "insurance_policy_invoice_poc"


def post_init_hook(cr, registry):
    env = api.Environment(cr, SUPERUSER_ID, {})

    # Create mail template if missing
    template = env["mail.template"].search([("name", "=", "Insurance Invoice - Customer Email")], limit=1)
    if not template:
        template = env["mail.template"].create({
            "name": "Insurance Invoice - Customer Email",
            "model_id": env.ref("account.model_account_move").id,
            "subject": "Your Invoice ${object.name}",
            "email_from": "${(object.company_id.email or user.email) | safe}",
            "email_to": "${object.partner_id.email or ''}",
            "body_html": '''
                <p>Hello ${object.partner_id.name},</p>
                <p>Your invoice <b>${object.name}</b> has been created and posted.</p>
                <p>Total: <b>${object.amount_total} ${object.currency_id.name}</b></p>
                <p>Thank you.</p>
            ''',
        })

    # Register xmlid for template (so env.ref works)
    imd = env["ir.model.data"].sudo()
    existing = imd.search([("module", "=", MODULE), ("name", "=", "mail_template_invoice_poc")], limit=1)
    if not existing:
        imd.create({
            "module": MODULE,
            "name": "mail_template_invoice_poc",
            "model": "mail.template",
            "res_id": template.id,
            "noupdate": True,
        })
