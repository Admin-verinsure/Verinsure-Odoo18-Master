from odoo import models
import requests

class PaymentTransactionAkahu(models.Model):
    _inherit = 'payment.transaction'

    def _get_specific_processing_values(self, processing_values):
        res = super()._get_specific_processing_values(processing_values)

        if self.provider_code == 'akahu':
            provider = self.provider_id

            headers = {
                "Authorization": f"Bearer {provider.akahu_app_token}"
            }

            payload = {
                "amount": self.amount,
                "currency": self.currency_id.name,
                "reference": self.reference,
            }

            # Example API call (implement actual endpoint)
            # response = requests.post(
            #     f"{provider.akahu_api_url}/payments",
            #     json=payload,
            #     headers=headers
            # )

            # res.update({'redirect_url': response.json().get('redirect_url')})

        return res
