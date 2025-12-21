# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import UserError


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

        if "insurance_details_id" in move_fields:
            move_vals["insurance_details_id"] = insurance.id

        candidates = ["insurance_id", "insurance_detail_id", "insurance_claim_id"]
        for fname in candidates:
            if fname in move_fields:
                f = move_fields[fname]
                if getattr(f, "comodel_name", None) == "insurance.details":
                    move_vals[fname] = insurance.id
                    move_vals["_cybro_link_field_used"] = fname
                    break
        return move_vals

    def _finalize_insurance_invoice_link(self, insurance, move, cybro_link_field_used=None):
        if cybro_link_field_used and cybro_link_field_used in move._fields:
            try:
                move.sudo().write({cybro_link_field_used: insurance.id})
            except Exception:
                pass
        if "invoice_ids" in insurance._fields:
            try:
                insurance.sudo().write({"invoice_ids": [(4, move.id)]})
            except Exception:
                pass

    # -------------------------
    # Helpers: Fill required ORM fields
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
    # Fix: ensure company_id is set (CRITICAL for currency list display)
    # -------------------------
    def _ensure_company_on_record(self, rec):
        if "company_id" in rec._fields:
            try:
                if not rec.company_id:
                    rec.sudo().write({"company_id": self.env.company.id})
            except Exception:
                pass

    # -------------------------
    # Fix: amount is related → write to the SOURCE field
    # -------------------------
    def _write_related_amount_source(self, insurance, amount_value):
        if "amount" not in insurance._fields:
            return {"written": False, "reason": "insurance.details has no amount field"}

        f = insurance._fields["amount"]

        related = getattr(f, "related", None)
        if not related:
            # not related, try direct write
            try:
                insurance.sudo().write({"amount": amount_value})
                return {"written": True, "path": "insurance.details.amount"}
            except Exception as e:
                return {"written": False, "reason": str(e)}

        # related is like ('policy_id', 'amount') or longer
        try:
            path = list(related)
        except Exception:
            return {"written": False, "reason": "Could not read related chain"}

        rec = insurance
        for step in path[:-1]:
            if step not in rec._fields:
                return {"written": False, "reason": f"Missing related step field: {step}"}
            rec = rec[step]
            if not rec:
                return {"written": False, "reason": f"Related step {step} is empty (False)"}

        target_field = path[-1]
        if target_field not in rec._fields:
            return {"written": False, "reason": f"Target field not found: {'.'.join(path)}"}

        # If target itself is related/computed, we still try write (may fail), but we can fallback below
        try:
            rec.sudo().write({target_field: amount_value})
            return {"written": True, "path": ".".join(path)}
        except Exception as e:
            # fallback: try common money fields on policy/details
            for fallback in ("amount", "premium", "sum_insured"):
                if fallback in rec._fields:
                    try:
                        rec.sudo().write({fallback: amount_value})
                        return {"written": True, "path": ".".join(path[:-1] + [fallback]), "fallback_used": True}
                    except Exception:
                        continue
            return {"written": False, "reason": str(e), "path": ".".join(path)}

    # -------------------------
    # Agent
    # -------------------------
    def _get_or_create_agent(self, employee_dict: dict):
        emp_name = (employee_dict.get("name") or "").strip()
        if not emp_name:
            raise UserError("Payload missing employee.name")
        emp_phone = (employee_dict.get("phone") or "").strip() or "0000000000"

        if "employee.details" in self.env:
            Emp = self.env["employee.details"].sudo()
            rec = Emp.search([("name", "=", emp_name)], limit=1)
            if not rec:
                vals = {"name": emp_name, "phone": emp_phone}
                if "user_id" in Emp._fields:
                    vals["user_id"] = self.env.user.id
                vals = self._build_required_vals(Emp, vals)
                vals["name"] = emp_name
                vals["phone"] = emp_phone
                rec = Emp.create(vals)
            return rec, "employee.details"

        if "hr.employee" in self.env:
            Emp = self.env["hr.employee"].sudo()
            rec = Emp.search([("name", "=", emp_name)], limit=1)
            if not rec:
                vals = {"name": emp_name}
                if "user_id" in Emp._fields:
                    vals["user_id"] = self.env.user.id
                vals = self._build_required_vals(Emp, vals)
                vals["name"] = emp_name
                rec = Emp.create(vals)
            return rec, "hr.employee"

        raise UserError("No employee model found (employee.details/hr.employee).")

    # -------------------------
    # Policy (auto-create safe)
    # -------------------------
    def _get_or_create_policy(self, policy_dict: dict):
        if "policy.details" not in self.env:
            raise UserError("policy.details model not found.")

        Policy = self.env["policy.details"].sudo()
        policy_dict = policy_dict or {}
        policy_id = policy_dict.get("id")
        policy_name = (policy_dict.get("name") or "").strip()

        if policy_id:
            try:
                rec = Policy.browse(int(policy_id))
                if rec.exists():
                    self._ensure_company_on_record(rec)
                    return rec
            except Exception:
                pass

        if policy_name:
            rec = Policy.search([("name", "=", policy_name)], limit=1)
            if rec:
                self._ensure_company_on_record(rec)
                return rec

        final_name = policy_name or "Default Policy"
        vals = {"name": final_name}
        vals = self._build_required_vals(Policy, vals)
        vals["name"] = final_name

        # set company/currency if available
        if "company_id" in Policy._fields and not vals.get("company_id"):
            vals["company_id"] = self.env.company.id
        if "currency_id" in Policy._fields and not vals.get("currency_id"):
            vals["currency_id"] = self.env.company.currency_id.id

        # handle NOT NULL policy_type_id (prod)
        if "policy_type_id" in Policy._fields and not vals.get("policy_type_id"):
            comodel = Policy._fields["policy_type_id"].comodel_name
            TypeModel = self.env[comodel].sudo()
            t = TypeModel.search([], limit=1)
            if not t:
                raise UserError(
                    "Policy Type master is empty. Create at least one Policy Type first "
                    "(required by policy_details.policy_type_id NOT NULL)."
                )
            vals["policy_type_id"] = t.id

        rec = Policy.create(vals)
        self._ensure_company_on_record(rec)
        return rec

    # -------------------------
    # Email sending (force visible mail + process queue)
    # -------------------------
    def _send_invoice_email_force(self, move, partner, email_to):
        # ensure email_from exists
        email_from = (self.env.company.email or self.env.user.email or "no-reply@" + (self.env.company.name or "example").replace(" ", "").lower() + ".com")

        mail = self.env["mail.mail"].sudo().create({
            "subject": f"Invoice {move.name}",
            "email_to": email_to,
            "email_from": email_from,
            "body_html": f"<p>Hello {partner.name},</p><p>Please find your invoice {move.name}.</p>",
            "auto_delete": False,
            "model": "account.move",
            "res_id": move.id,
        })

        # commit so you can see it even if send fails
        self.env.cr.commit()

        # send now
        mail.sudo().send(raise_exception=False)

        # force process queue (important when server works but queue not running)
        try:
            self.env["mail.mail"].sudo().process_email_queue()
        except Exception:
            pass

        mail = mail.sudo().browse(mail.id)  # refresh
        return mail.id, getattr(mail, "state", None), getattr(mail, "failure_reason", None)

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

        # Partner
        Partner = self.env["res.partner"].sudo()
        partner = Partner.search([("email", "ilike", cust_email)], limit=1)
        if not partner:
            partner = Partner.create({"name": cust_name, "email": cust_email, "customer_rank": 1})
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

        # Invoice numbers
        price_unit = float(inv.get("price_unit") or 0.0)
        qty = float(inv.get("qty") or 1.0)
        expected_total = price_unit * qty

        # Insurance create
        start_date = payload.get("start_date") or fields.Date.context_today(self)
        insurance_vals = {
            "partner_id": partner.id,
            "employee_id": emp_rec.id,
            "policy_id": policy_rec.id,
            "policy_duration": int(payload.get("policy_duration") or 12),
            "policy_number": int(payload.get("policy_number") or 0),
            "payment_type": payload.get("payment_type") or "fixed",
            "state": "draft",
            "start_date": start_date,
            "name": "/",
        }
        if "company_id" in self._fields:
            insurance_vals["company_id"] = company.id

        insurance = self.sudo().create(insurance_vals)

        # 🔥 ensure company is set (your current issue)
        self._ensure_company_on_record(insurance)

        # if currency_id exists, write it (even if related, write may fail silently -> ok)
        if "currency_id" in insurance._fields:
            try:
                insurance.sudo().write({"currency_id": currency.id})
            except Exception:
                pass

        # Confirm/sequence
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
        journal = self.env["account.journal"].sudo().search([("type", "=", "sale"), ("company_id", "=", company.id)], limit=1)
        if not journal:
            raise UserError("No Sales Journal found for this company.")

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

        # link invoice
        self._finalize_insurance_invoice_link(insurance, move, cybro_link_field_used)

        # ✅ FIX amount (your amount is related → set its source)
        amount_fix = self._write_related_amount_source(insurance, move.amount_total)

        # ✅ Email (force create + queue process)
        mail_id, mail_state, mail_failure_reason = self._send_invoice_email_force(move, partner, cust_email)

        return {
            "insurance_id": insurance.id,
            "insurance_name": insurance.name,
            "insurance_company_id": insurance.company_id.id if "company_id" in insurance._fields and insurance.company_id else None,
            "insurance_currency_id": insurance.currency_id.id if "currency_id" in insurance._fields and insurance.currency_id else None,
            "insurance_currency_name": insurance.currency_id.name if "currency_id" in insurance._fields and insurance.currency_id else None,
            "insurance_amount": getattr(insurance, "amount", None) if "amount" in insurance._fields else None,
            "amount_fix": amount_fix,
            "invoice_id": move.id,
            "invoice_name": move.name,
            "invoice_amount_total": move.amount_total,
            "mail_id": mail_id,
            "mail_state": mail_state,
            "mail_failure_reason": mail_failure_reason,
            "employee_model_used": employee_model_used,
            "confirm_method_tried": confirm_tried,
            "confirm_method_ran": confirm_ran,
            "forced_sequence": force_seq_info,
            "cybro_link_field_used": cybro_link_field_used,
        }
