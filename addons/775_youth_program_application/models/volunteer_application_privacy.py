from odoo import models, fields

class YouthVolunteerApplicationPrivacy(models.Model):
    _name = "youth.volunteer.application.privacy"
    _description = "Volunteer Application - Privacy Controlled (Section 1B)"
    _order = "create_date desc"

    application_id = fields.Many2one("youth.volunteer.application", required=True, ondelete="cascade", index=True)

    # Section 1B content (privacy-controlled)
    rotary_member = fields.Boolean(string="Member of Rotary/Rotaract club?")
    club_name_year_joined = fields.Char(string="Club name and year joined")
    linkedin_profile = fields.Char()
    facebook_profile = fields.Char()
    cv_attachment_id = fields.Many2one("ir.attachment", string="CV Attachment", help="Stored privately; internal access only.")

    criminal_q1 = fields.Boolean(string="Charged/convicted/pleaded guilty to any crimes?")
    criminal_q2 = fields.Boolean(string="Subject to any court order involving abuse/violence/harassment?")
    criminal_explain = fields.Text(string="If yes, please explain (dates, country, province/state)")
