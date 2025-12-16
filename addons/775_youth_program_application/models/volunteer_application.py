from odoo import models, fields, api
from odoo.exceptions import ValidationError

class YouthVolunteerApplication(models.Model):
    _name = "youth.volunteer.application"
    _description = "Youth Program Volunteer Application"
    _inherit = ["mail.thread", "mail.activity.mixin"]

    partner_id = fields.Many2one("res.partner", required=True, index=True, default=lambda self: self.env.user.partner_id)
    state = fields.Selection([
        ("draft", "Draft"),
        ("submitted", "Submitted"),
        ("reviewed", "Reviewed"),
    ], default="draft", tracking=True, index=True)

    # -----------------------------
    # SECTION 1A - Required for all
    # -----------------------------
    position_applied_for = fields.Char(string="Position applied for")
    full_name = fields.Char(required=True)
    address_line1 = fields.Char(string="Address")
    address_line2 = fields.Char(string="Address (line 2)")
    city = fields.Char()
    region = fields.Char(string="Region/State")
    postal_code = fields.Char()
    how_long_at_address = fields.Char(string="How long at this address")
    previous_addresses_notes = fields.Text(string="Previous residences (details / note)")
    mobile = fields.Char()
    phone = fields.Char()
    email = fields.Char()
    date_of_birth = fields.Date()
    id_provided = fields.Selection([
        ("dl", "Drivers licence"),
        ("passport", "Passport"),
        ("other", "Other"),
    ], string="Photo ID type")
    id_number = fields.Char(string="ID number")
    consent_ack = fields.Boolean(string="Consent to information checks (acknowledge)")
    waiver_ack = fields.Boolean(string="Waiver acknowledgement")
    applicant_signature_name = fields.Char(string="Applicant signature (type your full name)")
    applicant_signed_on = fields.Date(string="Applicant signed on")

    # Home Stay trigger (branched sections)
    is_homestay_volunteer = fields.Boolean(string="Involved in Home Stay programmes")

    # -----------------------------
    # SECTION 2B-2D - Only for Home Stay volunteers
    # Keep portal entry simple but structured.
    # -----------------------------
    employment_current = fields.Text(string="Employment history - current role (details)")
    employment_previous = fields.Text(string="Employment history - previous roles (details)")
    rotary_youth_program_history = fields.Text(string="Rotary youth program involvement (details)")
    youth_volunteer_history = fields.Text(string="Volunteer history with youth (details)")

    # References (3 slots)
    ref1_name = fields.Char(string="Reference 1 - Name")
    ref1_relationship = fields.Char(string="Reference 1 - Relationship")
    ref1_phone = fields.Char(string="Reference 1 - Phone")
    ref1_email = fields.Char(string="Reference 1 - Email")

    ref2_name = fields.Char(string="Reference 2 - Name")
    ref2_relationship = fields.Char(string="Reference 2 - Relationship")
    ref2_phone = fields.Char(string="Reference 2 - Phone")
    ref2_email = fields.Char(string="Reference 2 - Email")

    ref3_name = fields.Char(string="Reference 3 - Name")
    ref3_relationship = fields.Char(string="Reference 3 - Relationship")
    ref3_phone = fields.Char(string="Reference 3 - Phone")
    ref3_email = fields.Char(string="Reference 3 - Email")

    qualifications_training = fields.Text(string="Qualifications / training relevant to youth programs")
    homestay_confirmation_ack = fields.Boolean(string="Home Stay confirmation (acknowledge)")
    homestay_signature_name = fields.Char(string="Home Stay signature (type your full name)")
    homestay_signed_on = fields.Date(string="Home Stay signed on")

    # -----------------------------
    # SECTION 1C - Sponsor required for all
    # -----------------------------
    sponsor_name = fields.Char()
    sponsor_club = fields.Char()
    sponsor_years_known = fields.Char()
    sponsor_role = fields.Selection([
        ("president", "President"),
        ("governor", "District Governor"),
        ("chair", "District Chair"),
        ("other", "Other"),
    ])
    sponsor_role_other = fields.Char()
    sponsor_signature_name = fields.Char(string="Sponsor signature (type full name)")
    sponsor_signed_on = fields.Date(string="Sponsor signed on")

    # -----------------------------
    # SECTION 2E - District use only (internal)
    # -----------------------------
    district_police_check = fields.Boolean(string="Police check completed")
    district_reference_checks = fields.Boolean(string="Reference checks completed")
    district_home_visit = fields.Boolean(string="Home visit completed")
    district_notes = fields.Text(string="District notes")
    district_signed_by = fields.Many2one("res.users", string="District signed by")
    district_signed_on = fields.Date(string="District signed on")

    # Link to privacy record (Section 1B)
    privacy_id = fields.One2many("youth.volunteer.application.privacy", "application_id", string="Privacy record", readonly=True)

    # Portal helper
    can_edit_portal = fields.Boolean(compute="_compute_can_edit_portal")

    @api.depends("state")
    def _compute_can_edit_portal(self):
        for rec in self:
            rec.can_edit_portal = rec.state == "draft"

    def action_submit(self):
        for rec in self:
            if rec.state != "draft":
                continue
            rec._validate_before_submit()
            rec.state = "submitted"

    def _validate_before_submit(self):
        for rec in self:
            # Minimum required checks
            if not rec.full_name:
                raise ValidationError("Full name is required.")
            if not rec.consent_ack:
                raise ValidationError("You must acknowledge the consent section before submitting.")
            if not rec.waiver_ack:
                raise ValidationError("You must acknowledge the waiver section before submitting.")
            if not rec.applicant_signature_name or not rec.applicant_signed_on:
                raise ValidationError("Applicant signature name and date are required.")
            # Home stay required subset
            if rec.is_homestay_volunteer:
                if not rec.homestay_confirmation_ack:
                    raise ValidationError("Home Stay confirmation is required for Home Stay volunteers.")
                if not rec.homestay_signature_name or not rec.homestay_signed_on:
                    raise ValidationError("Home Stay signature name and date are required.")
