# your_module_name/controllers/main.py

from odoo.addons.auth_signup.controllers.main import AuthSignupHome as BaseSignup
from odoo import http

class AuthSignupHomeExtended(BaseSignup):
    """
    Keep the parent routes. Just ensure `rotary_id` from the form is:
      - present in the qcontext as `rotary_org_id` so the field renders
      - persisted on signup by mapping into the create vals
    """

    def get_auth_signup_qcontext(self):
        """Ensure rotary_org_id is available to the signup template."""
        q = super().get_auth_signup_qcontext()
        # Mirror (not pop) so validation / re-render still has original key too
        rid = q.get("rotary_id")
        if rid and "rotary_org_id" not in q:
            q["rotary_org_id"] = rid
        return q

    def _prepare_signup_values(self, qcontext):
        """Map rotary_id -> rotary_org_id at save time."""
        vals = super()._prepare_signup_values(qcontext)
        rid = (qcontext or {}).get("rotary_id")
        if rid:
            vals["rotary_org_id"] = rid
        return vals
