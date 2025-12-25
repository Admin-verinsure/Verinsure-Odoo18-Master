from odoo import models, fields, api
import json
import requests
import pytz

class FormSubmission(models.Model):
    _name = 'form.submission'
    _description = 'Form Submission'

    form_id = fields.Many2one('form.builder', string="Form", required=True, ondelete='cascade')
    submitted_data = fields.Json(string="Submitted Data")
    submitted_on = fields.Datetime(string="Submitted On", default=fields.Datetime.now)

    customer_email = fields.Char(string="Customer Email")

    submitted_on_local = fields.Char(string="Local Submitted Time", compute='_compute_submitted_on_local')

    def name_get(self):
        return [(record.id, f"Submission {record.id} - {record.submitted_on}") for record in self]

    def _validate_email_config(self):
        """Validate email configuration before sending"""
        errors = []
        
        if self.email_notifications_enabled:
            if self.send_to_owner and not self.created_by.email:
                errors.append("Form owner doesn't have an email address configured")
            
            if self.cc_emails:
                cc_emails = [email.strip() for email in self.cc_emails.split(',')]
                for email in cc_emails:
                    if email and '@' not in email:
                        errors.append(f"Invalid CC email address: {email}")
            
            if self.bcc_emails:
                bcc_emails = [email.strip() for email in self.bcc_emails.split(',')]
                for email in bcc_emails:
                    if email and '@' not in email:
                        errors.append(f"Invalid BCC email address: {email}")
        return errors

    def _process_address_fields(self, form_data, form_fields):
        """Process address field data into structured format"""
        processed_data = {}
        address_fields = {}
        
        for key, value in form_data.items():
            if '_street' in key or '_city' in key or '_state' in key or '_zip' in key or '_country' in key:
                parts = key.split('_')
                if len(parts) >= 3:
                    field_id = parts[1]
                    component = parts[2]
                    
                    if field_id not in address_fields:
                        address_fields[field_id] = {}
                    address_fields[field_id][component] = value
            else:
                processed_data[key] = value
        
        for field_id, components in address_fields.items():
            field = form_fields.filtered(lambda f: str(f.id) == field_id and f.field_type == 'address')
            if field:
                address_parts = []
                if components.get('street'):
                    address_parts.append(components['street'])
                if components.get('city'):
                    address_parts.append(components['city'])
                if components.get('state'):
                    address_parts.append(components['state'])
                if components.get('zip'):
                    address_parts.append(components['zip'])
                if components.get('country'):
                    address_parts.append(components['country'])
                
                processed_data[f'field_{field_id}'] = ', '.join(address_parts) if address_parts else ''
                
                processed_data[f'field_{field_id}_components'] = components
        
        return processed_data

    def _format_submission_data_for_email(self):
        """Format submission data for email display"""
        if isinstance(self.submitted_data, str):
            import json
            data = json.loads(self.submitted_data)
        else:
            data = self.submitted_data or {}
            
        html = '<table style="border-collapse: collapse; width: 100%;">'
        html += '<thead><tr style="background-color: #f8f9fa;">'
        html += '<th style="border: 1px solid #dee2e6; padding: 8px; text-align: left;">Field</th>'
        html += '<th style="border: 1px solid #dee2e6; padding: 8px; text-align: left;">Value</th>'
        html += '</tr></thead><tbody>'
        
        for key, value in data.items():
            if key.startswith('field_') and not key.endswith('_components'):
                field_id = key.replace('field_', '')
                field = self.form_id.field_ids.filtered(lambda f: str(f.id) == field_id)
                if field:
                    html += f'<tr style="border: 1px solid #dee2e6;">'
                    html += f'<td style="border: 1px solid #dee2e6; padding: 8px; font-weight: bold;">{field.label}</td>'
                    
                    if field.field_type == 'file':
                        formatted_value = self._format_file_data_for_email(field, value)
                    elif field.field_type == 'address' and f'{key}_components' in data:
                        components = data[f'{key}_components']
                        formatted_value = '<div>'
                        if components.get('street'):
                            formatted_value += f"<div><strong>Street:</strong> {components['street']}</div>"
                        if components.get('city'):
                            formatted_value += f"<div><strong>City:</strong> {components['city']}</div>"
                        if components.get('state'):
                            formatted_value += f"<div><strong>State:</strong> {components['state']}</div>"
                        if components.get('zip'):
                            formatted_value += f"<div><strong>ZIP:</strong> {components['zip']}</div>"
                        if components.get('country'):
                            formatted_value += f"<div><strong>Country:</strong> {components['country']}</div>"
                        formatted_value += '</div>'
                    elif field.field_type == 'password':
                        formatted_value = '********'
                    else:
                        formatted_value = value if value else '<span style="color: #6c757d;">Not provided</span>'
                    
                    html += f'<td style="border: 1px solid #dee2e6; padding: 8px;">{formatted_value}</td>'
                    html += '</tr>'
                        
        html += '</tbody></table>'
        return html
    def _format_file_data_for_email(self, field, file_data):
        """Format file upload data for email display"""
        if not file_data:
            return '<span style="color: #6c757d;">No file uploaded</span>'
        
        html = '<div style="margin: 5px 0;">'
        
        if isinstance(file_data, list):
            html += f'<strong>{len(file_data)} file(s) uploaded:</strong><ul style="margin: 5px 0; padding-left: 20px;">'
            for file_info in file_data:
                if isinstance(file_info, dict):
                    filename = file_info.get('filename', 'Unknown')
                    size = len(file_info.get('content', '')) * 3 / 4 
                    size_kb = round(size / 1024, 2)
                    html += f'<li>{filename} ({size_kb} KB)</li>'
            html += '</ul>'
        elif isinstance(file_data, dict):
            filename = file_data.get('filename', 'Unknown')
            size = len(file_data.get('content', '')) * 3 / 4
            size_kb = round(size / 1024, 2)
            html += f'<strong>File:</strong> {filename} ({size_kb} KB)'
        
        html += '</div>'
        return html

    @api.depends('submitted_on')
    def _compute_submitted_on_local(self):
        for record in self:
            if record.submitted_on:
                user_tz = self.env.user.tz or 'UTC'
                timezone = pytz.timezone(user_tz)
                utc_time = pytz.UTC.localize(record.submitted_on)
                local_time = utc_time.astimezone(timezone)
                record.submitted_on_local = local_time.strftime('%Y-%m-%d %I:%M:%S %p')
            else:
                record.submitted_on_local = 'N/A'

   

    def validate_captcha(self, response):
        secret_key = self.captcha_secret_key
        url = "https://www.google.com/recaptcha/api/siteverify"
        data = {
            'secret': secret_key,
            'response': response
        }
        res = requests.post(url, data=data)
        return res.json().get('success', False)
