import html
from odoo import models

class ReportUtils(models.AbstractModel):
    _name = "report.utils"
    _description = "Report Helper Utilities"

    def clean_text(self, text):
        """Clean narration text but keep HTML structure for rendering"""
        if not text:
            return ""

        # Decode HTML entities (&nbsp; -> space)
        text = html.unescape(text)

        # Replace stray characters
        text = text.replace("Â", " ").replace(u"\xa0", " ")

        return text.strip()
