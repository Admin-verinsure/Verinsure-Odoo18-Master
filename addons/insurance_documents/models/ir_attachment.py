from odoo import fields, models

class IrAttachment(models.Model):
    _inherit = "ir.attachment"

    # Marks attachments created/managed via the Insurance Documents module
    x_insurance_doc = fields.Boolean(string="Insurance Document", index=True, default=False)
