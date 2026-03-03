from odoo import models, fields

class PaymentProviderAkahu(models.Model):
    _inherit = 'payment.provider'

    code = fields.Selection(
        selection_add=[('akahu', "Akahu")],
        ondelete={'akahu': 'set default'}
    )

    akahu_app_token = fields.Char("Akahu App Token")
    akahu_user_token = fields.Char("Akahu User Token")

    def _get_default_payment_method_codes(self):
        res = super()._get_default_payment_method_codes()
        if self.code == 'akahu':
            return ['electronic']
        return res
