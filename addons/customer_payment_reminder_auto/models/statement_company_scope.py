from odoo import models


class AccountMove(models.Model):
    _inherit = 'account.move'

    def search(self, domain, offset=0, limit=None, order=None, **kwargs):
        company_id = self.env.context.get('payment_reminder_company_id')
        if company_id:
            domain = list(domain or []) + [('company_id', '=', company_id)]
        return super().search(domain, offset=offset, limit=limit, order=order, **kwargs)


class AccountPayment(models.Model):
    _inherit = 'account.payment'

    def search(self, domain, offset=0, limit=None, order=None, **kwargs):
        company_id = self.env.context.get('payment_reminder_company_id')
        if company_id:
            domain = list(domain or []) + [('company_id', '=', company_id)]
        return super().search(domain, offset=offset, limit=limit, order=order, **kwargs)
