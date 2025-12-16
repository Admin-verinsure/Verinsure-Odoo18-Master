from odoo import http
from odoo.http import request
import base64

class YouthVolunteerPortal(http.Controller):

    def _get_or_create_app(self):
        App = request.env["youth.volunteer.application"]
        app = App.search([("partner_id", "=", request.env.user.partner_id.id)], limit=1)
        if not app:
            app = App.create({
                "partner_id": request.env.user.partner_id.id,
                "full_name": request.env.user.partner_id.name,
                "email": request.env.user.partner_id.email,
                "mobile": request.env.user.partner_id.mobile,
                "phone": request.env.user.partner_id.phone,
            })
        return app

    def _get_or_create_privacy(self, app):
        Privacy = request.env["youth.volunteer.application.privacy"].sudo()
        priv = Privacy.search([("application_id", "=", app.id)], limit=1)
        if not priv:
            priv = Privacy.create({"application_id": app.id})
        return priv

    @http.route(['/my/volunteer-application'], type='http', auth="user", website=True)
    def volunteer_application_form(self, **kw):
        app = self._get_or_create_app()
        priv = self._get_or_create_privacy(app)
        return request.render("775_youth_program_application.portal_volunteer_application_form", {
            "app": app,
            "priv": priv,
        })

    @http.route(['/my/volunteer-application/save'], type='http', auth="user", website=True, methods=["POST"])
    def volunteer_application_save(self, **post):
        app = self._get_or_create_app()
        if app.state != "draft":
            return request.redirect("/my/volunteer-application")

        # Record rules also enforce write only in draft for portal users.
        vals = {
            "position_applied_for": post.get("position_applied_for") or False,
            "full_name": post.get("full_name") or False,
            "address_line1": post.get("address_line1") or False,
            "address_line2": post.get("address_line2") or False,
            "city": post.get("city") or False,
            "region": post.get("region") or False,
            "postal_code": post.get("postal_code") or False,
            "how_long_at_address": post.get("how_long_at_address") or False,
            "previous_addresses_notes": post.get("previous_addresses_notes") or False,
            "mobile": post.get("mobile") or False,
            "phone": post.get("phone") or False,
            "email": post.get("email") or False,
            "date_of_birth": post.get("date_of_birth") or False,
            "id_provided": post.get("id_provided") or False,
            "id_number": post.get("id_number") or False,

            "consent_ack": True if post.get("consent_ack") else False,
            "waiver_ack": True if post.get("waiver_ack") else False,
            "applicant_signature_name": post.get("applicant_signature_name") or False,
            "applicant_signed_on": post.get("applicant_signed_on") or False,

            "is_homestay_volunteer": True if post.get("is_homestay_volunteer") else False,
            "employment_current": post.get("employment_current") or False,
            "employment_previous": post.get("employment_previous") or False,
            "rotary_youth_program_history": post.get("rotary_youth_program_history") or False,
            "youth_volunteer_history": post.get("youth_volunteer_history") or False,

            "ref1_name": post.get("ref1_name") or False,
            "ref1_relationship": post.get("ref1_relationship") or False,
            "ref1_phone": post.get("ref1_phone") or False,
            "ref1_email": post.get("ref1_email") or False,
            "ref2_name": post.get("ref2_name") or False,
            "ref2_relationship": post.get("ref2_relationship") or False,
            "ref2_phone": post.get("ref2_phone") or False,
            "ref2_email": post.get("ref2_email") or False,
            "ref3_name": post.get("ref3_name") or False,
            "ref3_relationship": post.get("ref3_relationship") or False,
            "ref3_phone": post.get("ref3_phone") or False,
            "ref3_email": post.get("ref3_email") or False,

            "qualifications_training": post.get("qualifications_training") or False,
            "homestay_confirmation_ack": True if post.get("homestay_confirmation_ack") else False,
            "homestay_signature_name": post.get("homestay_signature_name") or False,
            "homestay_signed_on": post.get("homestay_signed_on") or False,

            "sponsor_name": post.get("sponsor_name") or False,
            "sponsor_club": post.get("sponsor_club") or False,
            "sponsor_years_known": post.get("sponsor_years_known") or False,
            "sponsor_role": post.get("sponsor_role") or False,
            "sponsor_role_other": post.get("sponsor_role_other") or False,
            "sponsor_signature_name": post.get("sponsor_signature_name") or False,
            "sponsor_signed_on": post.get("sponsor_signed_on") or False,
        }
        app.write(vals)

        # Privacy record is sudo + locked from portal read; but portal can submit it here
        priv = self._get_or_create_privacy(app)
        priv_vals = {
            "rotary_member": True if post.get("rotary_member") else False,
            "club_name_year_joined": post.get("club_name_year_joined") or False,
            "linkedin_profile": post.get("linkedin_profile") or False,
            "facebook_profile": post.get("facebook_profile") or False,
            "criminal_q1": True if post.get("criminal_q1") else False,
            "criminal_q2": True if post.get("criminal_q2") else False,
            "criminal_explain": post.get("criminal_explain") or False,
        }

        # Handle CV upload (optional)
        upload = request.httprequest.files.get("cv_file")
        if upload and upload.filename:
            upload.stream.seek(0)
            data = upload.read()
            attachment = request.env["ir.attachment"].sudo().create({
                "name": upload.filename,
                "datas": base64.b64encode(data),
                "mimetype": upload.mimetype,
            })
            priv_vals["cv_attachment_id"] = attachment.id

        priv.write(priv_vals)

        return request.redirect("/my/volunteer-application")

    @http.route(['/my/volunteer-application/submit'], type='http', auth="user", website=True, methods=["POST"])
    def volunteer_application_submit(self, **post):
        app = self._get_or_create_app()
        if app.state == "draft":
            app.action_submit()
        return request.redirect("/my/volunteer-application")
