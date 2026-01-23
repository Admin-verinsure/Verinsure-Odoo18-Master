from odoo import fields, models

class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    sfb_ldap_enabled = fields.Boolean(string="Enable LDAP Enrichment (Forms)", config_parameter="sfb.ldap.enabled")
    sfb_ldap_server_uri = fields.Char(string="LDAP Server URI", config_parameter="sfb.ldap.server_uri")
    sfb_ldap_bind_dn = fields.Char(string="LDAP Bind DN", config_parameter="sfb.ldap.bind_dn")
    sfb_ldap_bind_password = fields.Char(string="LDAP Bind Password", config_parameter="sfb.ldap.bind_password")
    sfb_ldap_base_dn = fields.Char(string="LDAP Base DN", config_parameter="sfb.ldap.base_dn")
    sfb_ldap_filter = fields.Char(
        string="LDAP Filter",
        help="Placeholders: {first_name}, {last_name}, {email}. Example: (&(givenName={first_name})(sn={last_name})(mail={email}))",
        config_parameter="sfb.ldap.filter",
        default="(&(givenName={first_name})(sn={last_name})(mail={email}))",
    )
