# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import UserError
import base64


class InsuranceDetails(models.Model):
    _inherit = "insurance.details"

    # -------------------------
    # Helpers: Confirm + Sequence
    # -------------------------
    def _try_confirm_and_sequence(self, insurance):
        tried = []
        for method in ("action_confirm", "button_confirm", "confirm", "action_validate"):
            if hasattr(insurance, method):
                tried.append(method)
                try:
                    getattr(insurance, method)()
                    return True, tried
                except Exception:
                    continue
        return False, tried

    def _force_ins_sequence_if_needed(self, insurance):
        if not insurance.name or insurance.name == "/":
            seq = self.env["ir.sequence"].sudo().search(
                ["|", ("prefix", "ilike", "INS"), ("name", "ilike", "Insurance")],
                order="id desc",
                limit=1,
            )
            if seq:
                nxt = seq.next_by_id()
                if nxt:
                    insurance.write({"name": nxt})
                    return {
                        "forced_sequence": True,
                        "sequence_id": seq.id,
                        "sequence_name": seq.name,
                        "new_name": nxt,
                    }
        return {"forced_sequence": False}

    # -------------------------
    # Helpers: Link invoice -> Insurance (Cybro)
    # -------------------------
    def _set_cybro_invoice_link_fields(self, move_vals, insurance):
        move_fields = self.env["account.move"]._fields

        # our custom explicit link (from your module)
        move_vals["insurance_details_id"] = insurance.id

        # Cybro inverse field (account.move -> insurance.details)
        candidates = ["insurance_id", "insurance_detail_id", "insurance_claim_id"]
        for fname in candidates:
            if fname in move_fields:
                f = move_fields[fname]
                if getattr(f, "comodel_name", None) == "insurance.details":
                    move_vals[fname] = insurance.id
                    move_vals["_cybro_link_field_used"] = fname
                    break

        return move_vals

    # -------------------------
    # Helpers: Fill ORM required fields (best-effort)
    # -------------------------
    def _build_required_vals(self, Model, base_vals: dict):
        vals = dict(base_vals or {})

        for fname, field in Model._fields.items():
            if not getattr(field, "required", False):
                continue
            if fname in vals and vals[fname] not in (False, None, ""):
                continue

            if fname == "company_id" and field.type == "many2one":
                vals[fname] = self.env.company.id
                continue

            if fname == "user_id" and field.type == "many2one":
                vals[fname] = self.env.user.id
                continue

            if field.type in ("char", "text"):
                vals[fname] = "N/A"
                continue

            if field.type == "selection":
                try:
                    sel = field.selection(self.env)
                except Exception:
                    sel = field.selection
                if sel:
                    vals[fname] = sel[0][0]
                continue

            if field.type in ("integer", "float", "monetary"):
                vals[fname] = 0
                continue

            if field.type == "boolean":
                vals[fname] = False
                continue

        return vals

    # -------------------------
    # Helpers: create agent safely
    # -------------------------
    def _get_or_create_agent(self, employee_dict: dict):
        emp_name = (employee_dict.get("name") or "").strip()
        if not emp_name:
            raise UserError("Payload missing employee.name")

        # DB NOT NULL in prod (employee_details.phone)
        emp_phone = (employee_dict.get("phone") or "").strip() or "0000000000"

        def ensure_user_link(rec, Model):
            if "user_id" in Model._fields:
                try:
                    if not rec.user_id:
                        rec.write({"user_id": self.env.user.id})
                except Exception:
                    pass

        if "employee.details" in self.env:
            Emp = self.env["employee.details"].sudo()
            emp_rec = Emp.search([("name", "=", emp_name)], limit=1)

            if not emp_rec:
                base_vals = {"name": emp_name, "phone": emp_phone}
                if "user_id" in Emp._fields:
                    base_vals["user_id"] = self.env.user.id
                vals = self._build_required_vals(Emp, base_vals)
                vals["name"] = emp_name
                vals["phone"] = emp_phone
                emp_rec = Emp.create(vals)
            else:
                ensure_user_link(emp_rec, Emp)
                try:
                    if hasattr(emp_rec, "phone") and not emp_rec.phone:
                        emp_rec.write({"phone": emp_phone})
                except Exception:
                    pass

            return emp_rec, "employee.details"

        if "hr.employee" in self.env:
            Emp = self.env["hr.employee"].sudo()
            emp_rec = Emp.search([("name", "=", emp_name)], limit=1)
            if not emp_rec:
                vals = {"name": emp_name}
                if "user_id" in Emp._fields:
                    vals["user_id"] = self.env.user.id
                vals = self._build_required_vals(Emp, vals)
                vals["name"] = emp_name
                emp_rec = Emp.create(vals)
            else:
                ensure_user_link(emp_rec, Emp)
            return emp_rec, "hr.employee"

        raise UserError("No employee model found (employee.details/hr.employee).")

    # -------------------------
    # Helpers: Policy (auto-create, prod safe)
    # -------------------------
    def _get_or_create_policy(self, policy_dict: dict):
        if "policy.details" not in self.env:
            raise UserError("policy.details model not found.")

        Policy = self.env["policy.details"].sudo()
        policy_dict = policy_dict or {}

        policy_id = policy_dict.get("id")
        policy_name = (policy_dict.get("name") or "").strip()

        # by ID
        if policy_id:
            try:
                rec = Policy.browse(int(policy_id))
                if rec.exists():
                    return rec
            except Exception:
                pass

        # by name
        if policy_name:
            rec = Policy.search([("name", "=", policy_name)], limit=1)
            if rec:
                return rec

        # auto-create
        final_name = policy_name or "Default Policy"
        vals = {"name": final_name}

        vals = self._build_required_vals(Policy, vals)
        vals["name"] = final_name

        if "company_id" in Policy._fields and not vals.get("company_id"):
            vals["company_id"] = self.env.company.id

        if "currency_id" in Policy._fields and not vals.get("currency_id"):
            vals["currency_id"] = self.env.company.currency_id.id

        if "amount" in Policy._fields and vals.get("amount") in (None, False, ""):
            vals["amount"] = 0.0

        # DB NOT NULL policy_type_id in your prod
        if "policy_type_id" in Policy._fields and not vals.get("policy_type_id"):
            comodel = Policy._fields["policy_type_id"].comodel_name
            TypeModel = self.env[comodel].sudo()
            default_type = TypeModel.search([], limit=1)
            if not default_type:
                raise UserError(
                    "Cannot auto-create Policy because no Policy Type exists. "
                    "Create at least one record in Policy Type master."
                )
            vals["policy_type_id"] = default_type.id

        return Policy.create(vals)

    # -------------------------
    # Helpers: write insurance amount from invoice
    # -------------------------
    def _sync_insurance_amount_from_invoice(self, insurance, move):
        inv_total = float(move.amount_total or 0.0)
        for fname in ("amount", "premium", "policy_amount", "total_amount"):
            if fname in insurance._fields:
                try:
                    insurance.sudo().write({fname: inv_total})
                    return fname, inv_total
                except Exception:
                    continue
        return None, inv_total

    # -------------------------
    # Helpers: pick mail server + email_from
    # -------------------------
    def _get_outgoing_server_and_from(self):
        MailServer = self.env["ir.mail_server"].sudo()
        server = MailServer.search([("active", "=", True)], order="sequence asc, id asc", limit=1)

        # strong defaults for email_from
        company = self.env.company.sudo()
        email_from = (
            (server and server.smtp_user) or
            company.email or
            (company.partner_id and company.partner_id.email) or
            self.env.user.email or
            "no-reply@localhost"
        )
        return server, email_from

    # -------------------------
    # Main RPC
    # -------------------------
    @api.model
    def rpc_create_insurance_invoice_and_email(self, payload: dict):
        customer = payload.get("customer") or {}
        employee = payload.get("employee") or {}
        policy = payload.get("policy") or {}
        inv = payload.get("invoice") or {}

        cust_name = (customer.get("name") or "").strip()
        cust_email = (customer.get("email") or "").strip().lower()
        if not cust_name:
            raise UserError("Payload missing customer.name")
        if not cust_email:
            raise UserError("Payload missing customer.email")

        company = self.env.company
        target_state = (payload.get("state") or "confirmed").strip().lower()
        force_send = bool(payload.get("force_send", True))  # default True

        # Partner
        Partner = self.env["res.partner"].sudo()
        partner = Partner.search([("email", "ilike", cust_email)], limit=1)
        if not partner:
            try:
                partner = Partner.create({"name": cust_name, "email": cust_email, "customer_rank": 1})
            except Exception:
                partner = Partner.search([("email", "ilike", cust_email)], limit=1)
                if not partner:
                    raise
        else:
            if cust_name and partner.name != cust_name:
                partner.write({"name": cust_name})

        # Agent
        emp_rec, employee_model_used = self._get_or_create_agent(employee)

        # Policy
        policy_rec = self._get_or_create_policy(policy)

        # Currency
        currency_code = (payload.get("currency") or "AUD").strip()
        currency = self.env["res.currency"].sudo().search([("name", "=", currency_code)], limit=1)
        if not currency:
            raise UserError(f"Currency not found: {currency_code}")

        # Insurance
        start_date = payload.get("start_date") or fields.Date.context_today(self)
        insurance_vals = {
            "partner_id": partner.id,
            "employee_id": emp_rec.id,
            "policy_id": policy_rec.id,
            "policy_duration": int(payload.get("policy_duration") or 12),
            "currency_id": currency.id,
            "policy_number": int(payload.get("policy_number") or 0),
            "payment_type": payload.get("payment_type") or "fixed",
            "state": "draft",
            "start_date": start_date,
            "name": "/",
        }
        if "company_id" in self._fields:
            insurance_vals["company_id"] = company.id

        insurance = self.sudo().create(insurance_vals)

        confirm_ran = False
        confirm_tried = []
        force_seq_info = {"forced_sequence": False}

        if target_state in ("confirmed", "confirm", "validated", "posted"):
            confirm_ran, confirm_tried = self._try_confirm_and_sequence(insurance)
            if "state" in insurance._fields and insurance.state == "draft":
                insurance.write({"state": "confirmed"})
            force_seq_info = self._force_ins_sequence_if_needed(insurance)

        insurance_name = insurance.name

        # Product
        Product = self.env["product.product"].sudo()
        product = Product.search(
            [("sale_ok", "=", True), "|", ("company_id", "=", False), ("company_id", "=", company.id)],
            limit=1,
        )
        if not product:
            product = Product.create({"name": "Insurance Service", "type": "service", "sale_ok": True, "company_id": company.id})

        # Journal
        journal = self.env["account.journal"].sudo().search(
            [("type", "=", "sale"), ("company_id", "=", company.id)],
            limit=1,
        )
        if not journal:
            raise UserError("No Sales Journal found for this company.")

        price_unit = float(inv.get("price_unit") or 0.0)
        qty = float(inv.get("qty") or 1.0)

        # Invoice
        move_vals = {
            "move_type": "out_invoice",
            "company_id": company.id,
            "partner_id": partner.id,
            "currency_id": currency.id,
            "invoice_date": fields.Date.context_today(self),
            "journal_id": journal.id,
            "invoice_user_id": self.env.user.id,
            "invoice_origin": insurance_name,
            "ref": insurance_name,
            "invoice_line_ids": [(0, 0, {
                "product_id": product.id,
                "name": inv.get("line_name") or f"Insurance: {insurance_name}",
                "quantity": qty,
                "price_unit": price_unit,
            })],
        }
        move_vals = self._set_cybro_invoice_link_fields(move_vals, insurance)
        cybro_link_field_used = move_vals.pop("_cybro_link_field_used", None)

        move = self.env["account.move"].sudo().with_company(company).create(move_vals)
        move.action_post()

        # ✅ FIX #1: sync insurance amount from invoice
        amount_field_used, synced_amount = self._sync_insurance_amount_from_invoice(insurance, move)

        # Email PDF (force visible + logged)
        emailed = False
        email_error = None
        mail_id = None
        try:
            report = self.env["ir.actions.report"].sudo().search(
                [("model", "=", "account.move"), ("report_type", "=", "qweb-pdf")],
                limit=1,
            )
            if not report:
                raise UserError("No PDF report found for account.move.")

            ext = report.get_external_id()
            report_ref = ext.get(report.id)
            if not report_ref:
                raise UserError("Invoice report has no external id (xmlid).")

            pdf_content, _ = self.env["ir.actions.report"]._render_qweb_pdf(report_ref, res_ids=[move.id])

            attachment = self.env["ir.attachment"].sudo().create({
                "name": f"{move.name}.pdf",
                "type": "binary",
                "datas": base64.b64encode(pdf_content),
                "res_model": "account.move",
                "res_id": move.id,
                "mimetype": "application/pdf",
            })

            server, email_from = self._get_outgoing_server_and_from()

            mail_vals = {
                "subject": f"Invoice {move.name}",
                "email_from": email_from,             # ✅ ensures mail is created properly
                "email_to": cust_email,
                "body_html": f"<p>Hello {partner.name},</p><p>Please find your invoice attached.</p>",
                "attachment_ids": [(4, attachment.id)],
            }
            mail = self.env["mail.mail"].sudo().create(mail_vals)
            mail_id = mail.id

            # ✅ ensures it either sends or raises a visible error
            if server:
                mail.sudo().send(raise_exception=True, smtp_server_id=server.id)
            else:
                mail.sudo().send(raise_exception=True)

            emailed = True

        except Exception as e:
            emailed = False
            email_error = str(e)

        return {
            "insurance_id": insurance.id,
            "insurance_name": insurance.name,
            "insurance_state": insurance.state if "state" in insurance._fields else None,
            "insurance_currency": insurance.currency_id.name if insurance.currency_id else None,
            "insurance_amount_synced": synced_amount,
            "insurance_amount_field_used": amount_field_used,
            "invoice_id": move.id,
            "invoice_name": move.name,
            "invoice_origin": move.invoice_origin,
            "emailed_to": cust_email,
            "mail_id": mail_id,
            "emailed": emailed,
            "email_error": email_error,
            "employee_model_used": employee_model_used,
            "confirm_method_tried": confirm_tried,
            "confirm_method_ran": confirm_ran,
            "forced_sequence": force_seq_info,
            "cybro_link_field_used": cybro_link_field_used,
        }
