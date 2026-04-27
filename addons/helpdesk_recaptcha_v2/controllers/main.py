import requests
from odoo.addons.website_form.controllers.main import WebsiteForm
from odoo.http import request


class WebsiteFormCaptchaV2(WebsiteForm):

    def website_form(self, model_name, **kwargs):
        # Apply only to Helpdesk
        if model_name == 'helpdesk.ticket':

            recaptcha_response = kwargs.get('g-recaptcha-response')

            if not recaptcha_response:
                return request.render('helpdesk_recaptcha_v2.captcha_error')

            secret_key = request.env['ir.config_parameter'].sudo().get_param('recaptcha_v2.secret_key')

            verification = requests.post(
                'https://www.google.com/recaptcha/api/siteverify',
                data={
                    'secret': secret_key,
                    'response': recaptcha_response
                }
            ).json()

            if not verification.get('success'):
                return request.render('helpdesk_recaptcha_v2.captcha_error')

        # ✅ THIS is the correct way
        return super().website_form(model_name, **kwargs)