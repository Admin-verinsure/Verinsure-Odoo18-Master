from odoo import models, fields
import uuid


class ProductProduct(models.Model):
    _inherit = "product.product"

    external_guid = fields.Char(
        string="External GUID",
        copy=False,
        index=True,
        default=lambda self: str(uuid.uuid4())
    )

    _sql_constraints = [
        ('external_guid_unique',
         'unique(external_guid)',
         'External GUID must be unique!')
    ]
