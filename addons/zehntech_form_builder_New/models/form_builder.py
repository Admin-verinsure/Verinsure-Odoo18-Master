from odoo import models, fields, api, _
from datetime import datetime
import uuid
import json
import logging
from odoo.exceptions import ValidationError
from odoo.tools.safe_eval import safe_eval
import qrcode
import io
import base64
import requests

_logger = logging.getLogger(__name__)


class FormBuilder(models.Model):
    _name = 'form.builder'
    _description = 'Form Builder'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(string='Form Title', required=True, help="Enter a descriptive title for your form", translate=True)
    _sql_constraints = [
        ('unique_form_title', 'unique(name)', 'Form title must be unique!')
        ]

    status = fields.Selection([
        ('draft', 'Draft'),
        ('published', 'Published'),
        ('unpublished', 'Unpublished')
    ], default='draft', string='Status', tracking=True, help="Current publication status of the form")
    created_by = fields.Many2one('res.users', string='Created By', default=lambda self: self.env.user, readonly=True, tracking=True, help="Form is created by")
    created_date = fields.Datetime(string='Created Date', default=fields.Datetime.now, readonly=True, tracking=True, help="Form created on this date")
    submission_count = fields.Integer(string='Submissions/Entries', compute='_compute_submission_count', store=True, help="Total number of form submissions received")

    field_ids = fields.One2many('form.builder.field', 'form_id', string='Fields')

    is_shared = fields.Boolean(string="Is Shared", default=False, help="Enable public sharing of this form")
    share_token = fields.Char(string="Public Token", readonly=True, copy=False, help="Unique token used for public form access")

    form_styles = fields.Text('Form Styles JSON', help="Stores customization settings")

    custom_styles = fields.Text('Custom Styles', help="Custom CSS styles for the form")

    total_views = fields.Integer(string='Total Views', default=0, readonly=True, help="Number of times the form has been viewed")
    conversion_rate = fields.Float(string='Conversion Rate (%)', compute='_compute_conversion_rate', store=True, help="Percentage of form views that resulted in submissions")

    submission_ids = fields.One2many('form.submission', 'form_id', string='Submissions')

    thank_you_message = fields.Text(string="Thank You Message", tracking=True, help="Custom message displayed after successful form submission", translate=True)  # Add this new field
    message_on_unpublish = fields.Text(string="Message to display when form is Unpublished", tracking=True,  help="Message shown to users when trying to access an unpublished form", translate=True)

    layout_type = fields.Selection(
        [('vertical', 'Vertical Layout (Default)'), 
        ('horizontal', 'Horizontal Layout')],
        default='vertical',
        string='Form Layout',
        help='Choose the default layout for form fields'
    )

    error_score = fields.Float(string='Error Score', compute='_compute_error_score', store=True, help="Percentage of incomplete form submissions")

    # ! Email configuration in form 

    email_notifications_enabled = fields.Boolean(string="Enable Email Notifications", default=False, tracking=True, help="Allow sending email notifications on form submission.")
    send_to_owner = fields.Boolean(string="Send to Form Owner", default=True, help="Notify the form owner on each submission.")
    send_to_customer = fields.Boolean(string="Send to Customer", default=False, help="Send a confirmation email to the customer.")
    cc_emails = fields.Char(string="CC Recipients", help="Comma-separated email addresses")
    bcc_emails = fields.Char(string="BCC Recipients", help="Comma-separated email addresses")

    owner_email_subject = fields.Char(string="Owner Email Subject", default="New Form Submission", help="Subject line for notification emails sent to form owner")
    owner_email_template = fields.Html(string="Owner Email Template", default=lambda self: self._get_default_owner_template())

    customer_email_subject = fields.Char(string="Customer Email Subject", default="Form Submission Confirmation", help="Subject line for confirmation emails sent to customers")
    customer_email_template = fields.Html(string="Customer Email Template", default=lambda self: self._get_default_customer_template())


    response_limit = fields.Selection([
        ('unlimited', 'Multiple responses allowed'),
        ('one_only', 'One response only (requires sign-in)')
    ], string="Response Limit", default='unlimited', help="Control how many times users can submit this form")

    require_email_consent = fields.Boolean(string="Always send email to customer", default=True, help="Force sending email to the customer after submission.")
    consent_text = fields.Char(string="Consent Text", default="Send me a confirmation email")

    # ! Form availability fields 

    availability_type = fields.Selection([
        ('always', 'Always Available'),
        ('between_dates', 'Between Dates'),
        ('between_datetime', 'Between Specific Date & Time')
    ], string="Form Availability", default='always', tracking=True, help="Set when this form is available for submissions")

    available_from_date = fields.Date(string="Available From Date", help="Form becomes available from this date")
    available_to_date = fields.Date(string="Available To Date", help="Form stops accepting submissions after this date")

    available_from_datetime = fields.Datetime(string="Available From Date & Time", help="Exact date and time when form becomes available")
    available_to_datetime = fields.Datetime(string="Available To Date & Time", help="Exact date and time when form stops accepting submissions")

    availability_message = fields.Text(string="Unavailable Message", 
        default="This form is currently not available. Please try again later.", help="Message displayed when form is not available", translate=True)

    # ! OR code fields

    qr_code_image = fields.Binary(string="QR Code", compute='_compute_qr_code', store=True, help="QR code for easy form access via mobile devices")
    qr_code_filename = fields.Char(string="QR Code Filename", compute='_compute_qr_code_filename', help="Filename for QR code download")



    def action_share_form(self):
        """Generate share URL and open it"""
        if not self.share_token:
            self.share_token = self._generate_share_token()
        
        if self.status == 'draft':
            self.write({'status': 'published'})

        self._compute_qr_code()
        
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        default_lang = self.env.user.lang[:2] if self.env.user.lang else 'en'
        share_url = f"{base_url}/form_builder/shared/{self.share_token}?lang={default_lang}"
        
        return {
            'type': 'ir.actions.act_url',
            'url': share_url,
            'target': 'new',
        }

    def action_view_responses(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_url',
            'target': 'self',
            'url': f'/form_builder/responses/{self.id}',
        }

    @api.depends('total_views', 'submission_count')
    def _compute_conversion_rate(self):
        for record in self:
            if record.total_views > 0:
                record.conversion_rate = (record.submission_count / record.total_views) * 100
            else:
                record.conversion_rate = 0.0

   
    @api.depends('submission_ids')
    def _compute_submission_count(self):
        for record in self:
            submissions = self.env['form.submission'].search_count([('form_id', '=', record.id)])
            record.submission_count = submissions

    def action_publish(self):
        self.write({'status': 'published'})
        self.message_post(
            body=f"Form has been published by {self.env.user.name}",
            message_type='notification'
        )

    def action_unpublish(self):
        self.write({'status': 'unpublished'})
        self.message_post(
            body=f"Form has been unpublished by {self.env.user.name}",
            message_type='notification'
        )

    def action_preview_form(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_url',
            'target': 'new',
            'url': f'/form_builder/preview/{self.id}',
    }

    def action_view_analytics(self):
        """Open form analytics dashboard"""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': f'Analytics - {self.name}',
            'res_model': 'form.analytics',
            'view_mode': 'graph,pivot,list',
            'domain': [('form_id', '=', self.id)],
            'context': {'default_form_id': self.id},
            'target': 'current',
        }

    def increment_view_count(self):
        """Increment form view count"""
        self.sudo().write({'total_views': self.total_views + 1})

    def save_form_styles(self, styles_data):
        """Save customization styles to database"""
        self.ensure_one()
        self.write({'form_styles': json.dumps(styles_data)})
        return True

    def get_form_styles(self):
        """Get saved customization styles"""
        self.ensure_one()
        if self.form_styles:
            return json.loads(self.form_styles)
        return {}

    def get_custom_styles(self):
        """Get custom styles for the form"""
        return self.custom_styles or ''

    @api.constrains('form_styles')
    def _check_form_styles_format(self):
        """Validate that form_styles is valid JSON"""
        for record in self:
            if record.form_styles:
                try:
                    json.loads(record.form_styles)
                except (ValueError, TypeError) as e:
                    raise ValidationError(f'Invalid form styles format: {str(e)}')


    def _generate_share_token(self):
        """Generate a unique token for sharing"""
        token = str(uuid.uuid4())
        return token


    @api.depends('submission_ids')
    def _compute_error_score(self):
        """Calculate error score based on form completion rates"""
        for record in self:
            if not record.field_ids:
                record.error_score = 0.0
                continue
                
            total_fields = len(record.field_ids.filtered(lambda f: f.field_type != 'button'))
            if total_fields == 0:
                record.error_score = 0.0
                continue
                
            error_count = 0
            for submission in record.submission_ids:
                submitted_data = submission.submitted_data
                
                if isinstance(submitted_data, str):
                    try:
                        import json
                        submitted_data = json.loads(submitted_data)
                    except (json.JSONDecodeError, TypeError):
                        submitted_data = {}
                elif not isinstance(submitted_data, dict):
                    submitted_data = {}
                
                filled_fields = len([v for v in submitted_data.values() if v and str(v).strip()])
                if filled_fields < total_fields:
                    error_count += 1
                    
            if record.submission_count > 0:
                record.error_score = (error_count / record.submission_count) * 100
            else:
                record.error_score = 0.0


    @api.constrains('send_to_customer', 'field_ids')
    def _check_customer_email_field(self):
        """Validate that at least one email field exists when send_to_customer is enabled"""
        for record in self:
            if record.send_to_customer:
                has_email_field = any(
                    field.field_type == 'email' 
                    for field in record.field_ids
                )
                if not has_email_field:
                    raise ValidationError(
                        "Cannot enable 'Send to Customer' option!\n\n"
                        "Please add at least one Email field to your form before "
                        "enabling customer email notifications."
                    )

    @api.onchange('send_to_customer')
    def _onchange_send_to_customer(self):
        """Provide warning when enabling send_to_customer without email field"""
        if self.send_to_customer:
            has_email_field = any(
                field.field_type == 'email' 
                for field in self.field_ids
            )
            if not has_email_field:
                return {
                    'warning': {
                        'title': _('Email Field Required'),
                        'message': _(
                            'Your form does not have any Email field yet.\n\n'
                            'Please add an Email field to collect customer email '
                            'addresses before enabling this option.'
                        )
                    }
                }

    def action_view_detailed_analytics(self):
        """Open detailed form analytics with filters"""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Detailed Analytics - %s', self.name),
            'res_model': 'form.analytics',
            'view_mode': 'graph,pivot,list',
            'domain': [('form_id', '=', self.id)],
            'context': {
                'default_form_id': self.id,
                'group_by': ['date:month'],
                'search_default_last_30_days': 1,
            },
            'target': 'current',
        }

    def action_view_regional_analytics(self):
        """Open regional analytics"""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Regional Analytics - %s', self.name),
            'res_model': 'form.regional.analytics',
            'view_mode': 'list,graph',
            'domain': [('form_id', '=', self.id)],
            'context': {'default_form_id': self.id},
            'target': 'current',
        }



    # ! Email notification methods 

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

    def _create_file_attachments(self, submission_data, submission_id):
        """Create ir.attachment records for uploaded files and return links"""
        attachment_links = {}
        
        for key, value in submission_data.items():
            if key.startswith('field_'):
                field_id = key.replace('field_', '')
                field = self.field_ids.filtered(lambda f: str(f.id) == field_id and f.field_type == 'file')
                
                if field and value:
                    files_data = value if isinstance(value, list) else [value]
                    file_links = []
                    
                    for file_data in files_data:
                        if isinstance(file_data, dict) and file_data.get('content'):
                            attachment = self.env['ir.attachment'].sudo().create({
                                'name': file_data['filename'],
                                'type': 'binary',
                                'datas': file_data['content'],
                                'res_model': 'form.submission',
                                'res_id': submission_id,
                                'mimetype': file_data.get('mimetype', 'application/octet-stream'),
                                'public': True,  # Make it publicly accessible
                            })
                            
                            base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
                            download_url = f"{base_url}/web/content/{attachment.id}?download=true"
                            
                            file_links.append({
                                'filename': file_data['filename'],
                                'url': download_url,
                                'attachment_id': attachment.id
                            })
                    
                    if file_links:
                        attachment_links[key] = file_links
        
        return attachment_links


    def _send_emails_async(self, submission_data):
        """Send emails in a new cursor to avoid blocking"""
        with self.pool.cursor() as new_cr:
            self_new = self.with_env(self.env(cr=new_cr))
            try:
                self_new.send_notification_emails(submission_data)
                new_cr.commit()
            except Exception as e:
                _logger.error(f'Async email sending failed: {str(e)}')
                new_cr.rollback()

    def send_notification_emails(self, submission_data,):
        """Send notification emails based on form settings"""
        if not self.email_notifications_enabled:
            return
            
        try:
            customer_email = None
            email_consent = submission_data.get('email_consent')

            if isinstance(email_consent, str):
                email_consent = email_consent.lower() in ['on', 'true', '1', 'yes']
            elif email_consent is None:
                email_consent = False
            else:
                email_consent = bool(email_consent)

            for key, value in submission_data.items():
                if key.startswith('field_'):
                    field_id = key.replace('field_', '')
                    field = self.field_ids.filtered(lambda f: str(f.id) == field_id and f.field_type == 'email')
                    if field and value and value.strip():
                        customer_email = value.strip()
                        break
            

            latest_submission = self.env['form.submission'].sudo().search(
                [('form_id', '=', self.id)], 
                order='id desc', 
                limit=1
            )
            file_links = self._create_file_attachments(submission_data, latest_submission.id if latest_submission else False)
            
            if self.send_to_owner and self.created_by.email:
                self._send_owner_notification(submission_data, file_links)  

            if self.send_to_customer and customer_email:
                if self.require_email_consent:
                    self._send_customer_notification(customer_email, submission_data, file_links)  # PASS file_links
                else:
                    if email_consent:
                        self._send_customer_notification(customer_email, submission_data, file_links)  # PASS file_links
                    else:
                        _logger.info(f'Customer email not sent - user did not check consent checkbox for form {self.name}')
            else:
                if not customer_email:
                    _logger.warning(f'No customer email found for form {self.name}')
                elif not self.send_to_customer:
                    _logger.info(f'Customer email sending disabled for form {self.name}')
                    
        except Exception as e:
            _logger.error(f'Error sending notification emails for form {self.name}: {str(e)}')

    def _send_owner_notification(self, submission_data, file_links=None):
        """Send email to form owner"""
        try:
            formatted_body = self._format_email_template(
                self.owner_email_template or self._get_default_owner_template(),
                submission_data,
                file_links
            )
            
            html_body = self._convert_text_to_html(formatted_body)
            
            mail_values = {
                'subject': self.owner_email_subject or f'New submission for {self.name}',
                'body_html': html_body,
                'email_to': self.created_by.email,
                'email_from': self.env.company.email or self.env.user.email or 'noreply@yourcompany.com',
                'reply_to': self.env.company.email or self.env.user.email,
                'subtype_id': self.env.ref('mail.mt_comment').id,
            }
            
            if self.cc_emails:
                cc_list = [email.strip() for email in self.cc_emails.split(',') if email.strip()]
                mail_values['email_cc'] = ','.join(cc_list)
            
            mail = self.env['mail.mail'].sudo().create(mail_values)
            mail.send()

            if self.bcc_emails:
                bcc_list = [email.strip() for email in self.bcc_emails.split(',') if email.strip()]
                for bcc_email in bcc_list:
                    bcc_mail_values = {
                        'subject': mail_values['subject'],
                        'body_html': mail_values['body_html'],
                        'email_to': bcc_email,
                        'email_from': mail_values['email_from'],
                        'reply_to': mail_values['reply_to'],
                        'subtype_id': mail_values['subtype_id'],
                    }
                    bcc_mail = self.env['mail.mail'].sudo().create(bcc_mail_values)
                    bcc_mail.send()
            
            
        except Exception as e:
            _logger.error(f'Failed to send owner notification: {str(e)}')

    def _send_customer_notification(self, customer_email, submission_data, file_links=None):
        """Send confirmation email to customer"""
        try:
            formatted_body = self._format_email_template(
                self.customer_email_template or self._get_default_customer_template(),
                submission_data,
                file_links
            )
            
            html_body = self._convert_text_to_html(formatted_body)
            
            mail_values = {
                'subject': self.customer_email_subject or f'Thank you for your submission - {self.name}',
                'body_html': html_body,
                'email_to': customer_email,
                'email_from': self.env.company.email or self.env.user.email or 'noreply@yourcompany.com',
                'reply_to': self.env.company.email or self.env.user.email,
                'subtype_id': self.env.ref('mail.mt_comment').id,
            }
            
            mail = self.env['mail.mail'].sudo().create(mail_values)
            mail.send()
                        
        except Exception as e:
            _logger.error(f'Failed to send customer notification to {customer_email}: {str(e)}')

    def _format_email_template(self, template, submission_data, file_links=None):
        """Format email template with submission data and file links"""
        import pytz
        
        formatted_data = ""
        
        for key, value in submission_data.items():
            if key.startswith('field_') and value:
                field_id = key.replace('field_', '').split('_')[0]
                field = self.field_ids.filtered(lambda f: str(f.id) == field_id)
                if field and field.field_type != 'captcha':
                    if field.field_type == 'password':
                        display_value = '*' * 8
                    elif field.field_type == 'file':
                        if file_links and key in file_links:
                            if len(file_links[key]) == 1:
                                file_info = file_links[key][0]
                                display_value = f"{file_info['filename']} [DOWNLOAD_{file_info['attachment_id']}]"
                            else:
                                file_items = []
                                for file_info in file_links[key]:
                                    file_items.append(f"• {file_info['filename']} [DOWNLOAD_{file_info['attachment_id']}]")
                                display_value = '\n   ' + '\n   '.join(file_items)
                        else:
                            display_value = 'No files'
                    else:
                        display_value = str(value)
                    
                    if field.field_type == 'checkbox' and display_value.lower() == 'on':
                        display_value = 'Yes'
                    
                    formatted_data += f"**{field.label}:** {display_value}\n"
        
        user_tz = self.env.user.tz or 'UTC'
        timezone = pytz.timezone(user_tz)
        
        utc_now = pytz.UTC.localize(fields.Datetime.now())
        local_now = utc_now.astimezone(timezone)
        
        template = template.replace('{{form_name}}', self.name or 'Form')
        template = template.replace('{{submission_data}}', formatted_data)
        template = template.replace('{{date}}', local_now.strftime('%B %d, %Y at %I:%M %p'))
        
        return template
        

    def _convert_text_to_html(self, text):
        """Convert plain text with markdown-style formatting to HTML"""
        import re
        
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        
        html = '<div style="font-family: Arial, sans-serif; line-height: 1.6; color: #333; padding: 20px;">'
        lines = text.strip().split('\n')
        
        for line in lines:
            line = line.strip()
            if not line:
                html += '<br/>'
                continue
            
            line = re.sub(r'\*\*(.*?)\*\*', r'\1', line)
            
            def replace_download_link(match):
                attachment_id = match.group(1)
                attachment = self.env['ir.attachment'].sudo().browse(int(attachment_id))
                if attachment.exists():
                    download_url = f"{base_url}/web/content/{attachment_id}?download=true"
                    return (f'<a href="{download_url}" '
                        f'style="display: inline-block;'
                        f'padding: 6px 12px; text-decoration: none; border-radius: 4px; '
                        f'font-size: 13px; margin-left: 8px;">📥 Download</a>')
                return ''
            
            line = re.sub(r'\[DOWNLOAD_(\d+)\]', replace_download_link, line)
            
            if '•' in line:
                html += f'<p style="margin: 4px 0; padding-left: 20px; color: #555;">{line}</p>'
            else:
                html += f'<p style="margin: 8px 0;">{line}</p>'
        
        html += '</div>'
        return html

    def _get_default_owner_template(self):
        return """
            <div style="background: #f8f9fa; padding: 20px; border-radius: 8px; margin-bottom: 20px;">
                <h2 style="color: #007bff; margin: 0 0 10px 0;">**New Form Submission Received**</h2>
                <p style="margin: 0; color: #666;">**Form:** {{form_name}}</p>
                <p style="margin: 5px 0 0 0; color: #666;">**Submitted:** {{date}}</p>
            </div>

    **Submitted Information:**
    {{submission_data}}
<div>
            <div style="margin-top: 20px; padding: 15px;  border-radius: 8px;">
                <p style="margin-left: auto; margin-right:auto; color: #666; font-size: 14px;">
                    This is an automated notification from your form builder system.
                </p>
            </div>
</div>
        """

    def _get_default_customer_template(self):
        return """
            
                <div style="">
                <h2 style="margin: 0 0 0 0; background: #28a745; color: white; padding: 20px; border-radius: 8px; margin-bottom: 10px; text-align: center;">Thank You for Your Submission!</h2>
                <p style="margin: 0; opacity: 0.9; background: #d4edda; color: #155724; padding: 20px; border-radius: 8px; margin-bottom: 10px; text-align: center;">We have successfully received your information.</p>
                </div>

                    <p style="margin: 0 0 0 0; background: #f8f9fa; padding: 5px; border-radius: 8px;">Form: {{form_name}}</p>
                    <p style="margin: 0; background: #f8f9fa; padding: 5px; border-radius: 8px;">Submitted: {{date}}</p>
 

    **Your Submitted Information:**
    {{submission_data}}

                <p style="margin-left: auto; margin-right:auto; color: #856404; margin-top: 5px; padding: 15px; border-radius: 8px; text-align: center; padding-bottom:0;">
                   What's Next?
                </p>
                 <p style="margin-left: auto; margin-right:auto; color: #856404; margin-top: 5px; padding: 15px; border-radius: 8px; text-align: center; padding-bottom:0;">
                   We will review your submission and get back to you soon. Thank you for choosing us!
                </p>

    """

    def _create_mail_template_if_not_exists(self):
        """Create mail template for form submissions"""
        template_name = f'Form Submission - {self.name}'
        existing_template = self.env['mail.template'].search([('name', '=', template_name)], limit=1)
        
        if not existing_template:
            template = self.env['mail.template'].create({
                'name': template_name,
                'model_id': self.env['ir.model'].search([('model', '=', 'form.submission')]).id,
                'subject': '{{object.form_id.owner_email_subject or "New Form Submission"}}',
                'body_html': '''
                <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
                    <div style="background: #f8f9fa; padding: 20px; border-radius: 8px; margin-bottom: 20px;">
                        <h2 style="color: #007bff; margin: 0 0 10px 0;">New Form Submission Received</h2>
                        <p style="margin: 0; color: #666;">Form: {{object.form_id.name}}</p>
                        <p style="margin: 5px 0 0 0; color: #666;">Submitted on: {{object.submitted_on}}</p>
                    </div>
                    <div style="background: white; border: 1px solid #ddd; border-radius: 8px; padding: 20px;">
                        <h3 style="color: #333; margin: 0 0 15px 0;">Submitted Information:</h3>
                        {{object._format_submission_data_for_email()}}
                    </div>
                </div>
                ''',
                'email_from': '{{user.email}}',
                'use_default_to': True,
            })
            return template
        return existing_template

    def check_response_limit(self, user_email=None):
        """Check if user can submit based on response limits"""
        if self.response_limit == 'unlimited':
            return True
            
        if self.response_limit == 'one_only':
            if not user_email:
                return False
            
            existing = self.env['form.submission'].sudo().search([
                ('form_id', '=', self.id),
                ('customer_email', '=', user_email)
            ])
            return len(existing) == 0
        
        return True

# ! Form availablity methods 

    def is_form_available(self):
        """Check if form is currently available based on availability settings"""
        if self.availability_type == 'always':
            return True
        
        now = fields.Datetime.now()
        today = fields.Date.today()
        
        if self.availability_type == 'between_dates':
            if not (self.available_from_date and self.available_to_date):
                return False
            return self.available_from_date <= today <= self.available_to_date
        
        elif self.availability_type == 'between_datetime':
            if not (self.available_from_datetime and self.available_to_datetime):
                return False
            return self.available_from_datetime <= now <= self.available_to_datetime
        
        return True

    @api.constrains('available_from_date', 'available_to_date')
    def _check_date_range(self):
        for record in self:
            if record.availability_type == 'between_dates':
                if record.available_from_date and record.available_to_date:
                    if record.available_from_date > record.available_to_date:
                        raise ValidationError("'Available From Date' cannot be later than 'Available To Date'")

    @api.constrains('available_from_datetime', 'available_to_datetime') 
    def _check_datetime_range(self):
        for record in self:
            if record.availability_type == 'between_datetime':
                if record.available_from_datetime and record.available_to_datetime:
                    if record.available_from_datetime > record.available_to_datetime:
                        raise ValidationError("'Available From DateTime' cannot be later than 'Available To DateTime'")
    
    availability_status = fields.Char(string="Availability", compute='_compute_availability_status')

    @api.depends('availability_type', 'available_from_date', 'available_to_date', 
                'available_from_datetime', 'available_to_datetime')
    def _compute_availability_status(self):
        for record in self:
            if record.availability_type == 'always':
                record.availability_status = 'Always Available'
            elif record.availability_type == 'between_dates':
                if record.available_from_date and record.available_to_date:
                    if record.is_form_available():
                        record.availability_status = 'Available Now'
                    else:
                        record.availability_status = 'Not Available'
                else:
                    record.availability_status = 'Dates Not Set'
            elif record.availability_type == 'between_datetime':
                if record.available_from_datetime and record.available_to_datetime:
                    if record.is_form_available():
                        record.availability_status = 'Available Now'
                    else:
                        record.availability_status = 'Not Available'
                else:
                    record.availability_status = 'DateTime Not Set'
            else:
                record.availability_status = 'Unknown'


    # ! Chatter and tracker

    @api.model_create_multi
    def create(self, vals_list):
        """Override create to log form creation"""
        records = super().create(vals_list)
        for record in records:
            record.message_post(
                body=f"Form '{record.name}' has been created.",
                message_type='notification'
            )
        return records

    def write(self, vals):
        """Override write to track specific changes"""
        for record in self:
            if 'field_ids' in vals:
                record._track_field_changes(vals['field_ids'])
        
        result = super().write(vals)
        return result

    def _track_field_changes(self, field_changes):
        """Track changes to form fields"""
        for change in field_changes:
            if change[0] == 0:
                field_data = change[2]
                self.message_post(
                    body=f"New field added: '{field_data.get('label', 'Unnamed')}' ({field_data.get('field_type', 'unknown')} type)",
                    message_type='notification'
                )
            elif change[0] == 1:  
                field_id = change[1]
                field_data = change[2]
                field_obj = self.env['form.builder.field'].browse(field_id)
                changes_text = []
                
                if 'label' in field_data:
                    changes_text.append(f"label changed to '{field_data['label']}'")
                if 'field_type' in field_data:
                    changes_text.append(f"type changed to '{field_data['field_type']}'")
                if 'required' in field_data:
                    req_text = "made required" if field_data['required'] else "made optional"
                    changes_text.append(req_text)
                
                if changes_text:
                    self.message_post(
                        body=f"Field '{field_obj.label}' updated: {', '.join(changes_text)}",
                        message_type='notification'
                    )
            elif change[0] == 2:
                field_id = change[1]
                field_obj = self.env['form.builder.field'].browse(field_id)
                self.message_post(
                    body=f"Field '{field_obj.label}' has been removed",
                    message_type='notification'
                )

    # ! OR code methods 
    @api.depends('share_token')
    def _compute_qr_code(self):
        """Generate QR code for form's public URL"""
        for record in self:
            if record.share_token:
                base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
                form_url = f"{base_url}/form_builder/shared/{record.share_token}"
                
                qr = qrcode.QRCode(
                    version=1,
                    error_correction=qrcode.constants.ERROR_CORRECT_L,
                    box_size=10,
                    border=4,
                )
                qr.add_data(form_url)
                qr.make(fit=True)
                
                img = qr.make_image(fill_color="black", back_color="white")
                
                buffer = io.BytesIO()
                img.save(buffer, format='PNG')
                buffer.seek(0)
                
                record.qr_code_image = base64.b64encode(buffer.getvalue())
            else:
                record.qr_code_image = False

    @api.depends('name')
    def _compute_qr_code_filename(self):
        """Generate filename for QR code download"""
        for record in self:
            if record.name:
                clean_name = "".join(c for c in record.name if c.isalnum() or c in (' ', '-', '_')).rstrip()
                record.qr_code_filename = f"{clean_name}_QR_Code.png"
            else:
                record.qr_code_filename = "Form_QR_Code.png"

    def action_download_qr_code(self):
        """Download QR code as PNG file"""
        self.ensure_one()
        if not self.qr_code_image:
            return
        
        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content?model=form.builder&id={self.id}&field=qr_code_image&filename={self.qr_code_filename}&download=true',
            'target': 'new',
        }

    def action_copy_qr_url(self):
        """Return the form URL for copying"""
        self.ensure_one()
        if self.share_token:
            base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
            form_url = f"{base_url}/form_builder/shared/{self.share_token}"
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Form URL',
                    'message': f'Form URL: {form_url}',
                    'type': 'info',
                    'sticky': True,
                }
            }


class FormBuilderField(models.Model):
    _name = 'form.builder.field'
    _description = 'Form Builder Field'
    _order = 'sequence, id'
    _inherit = ['mail.thread']

    form_id = fields.Many2one('form.builder', string="Form", required=True, ondelete='cascade')
    label = fields.Char(string="Label", required=True, tracking=True, help="Display label for this form field", translate=True)
    placeholder = fields.Char(string="Placeholder", help="Placeholder text shown inside the input field", translate=True)
    field_type = fields.Selection([
        ('text', 'Text'),
        ('email', 'Email'),
        ('number', 'Number'),
        ('password', 'Password'),
        ('date', 'Date'),
        ('time', 'Time'),
        ('month', 'Month'),
        ('year', 'Year'),
        ('checkbox', 'Checkbox'),
        ('textarea', 'Textarea'),
        ('phone', 'Phone'),
        ('select', 'Dropdown'),
        ('radio', 'Radio Button'),
        ('url', 'URL/Link'),
        ('address', 'Address'),
        ('rating', 'Rating'),
        ('file', 'File Upload'),
        ('button', 'Button'),
        ('captcha', 'Captcha'),
    ], string="Field Type", default='text', required=True, tracking=True, help="Choose the type of a field")
    help_text = fields.Char(string="Help Text", help="Additional help text displayed below the field")
    required = fields.Boolean(string="Required", tracking=True, help="Choose weather to make field required or not")
    sequence = fields.Integer(string="Sequence", default=10, help="Order in which fields appear on the form")

    button_label = fields.Char(string="Button Label", help="Text displayed on the button")
    
    phone_min_length = fields.Integer("Phone Min Length", default=10, help="Minimum digits required in phone number")
    phone_max_length = fields.Integer("Phone Max Length", default=15, help="Maximum digits allowed in phone number")
    phone_country_code = fields.Many2one('res.country', string="Country Code")
    phone_hover_text = fields.Char("Phone Hover Text", help="Tooltip text for phone field")

    phone_show_country_selector = fields.Boolean("Show Country Code Selector", default=True, help="Show a dropdown for country codes in phone field.")

    text_min_length = fields.Integer("Text Min Length", help="Minimum number of characters required")
    text_max_length = fields.Integer("Text Max Length", help="Maximum number of characters allowed")
    text_pattern = fields.Char("Text Pattern (Regex)", help="Regular expression pattern for input validation")
    
    number_min_value = fields.Float("Number Min Value", help="Minimum numeric value allowed")
    number_max_value = fields.Float("Number Max Value", help="Maximum numeric value allowed")
    number_step = fields.Float("Number Step", default=1, help="Step increment for numeric input")
    
    textarea_rows = fields.Integer("Textarea Rows", default=3, help="Number of visible text rows")
    textarea_max_chars = fields.Integer("Textarea Max Characters", help="Maximum characters allowed in textarea")
    
    option_values = fields.Text("Options (one per line)", help="Enter one option per line.")

    # Dynamic dropdown options (optional)
    option_source = fields.Selection([
        ('manual', 'Manual'),
        ('model', 'From Model'),
    ], string="Options Source", default='manual', help="Choose how dropdown options are populated.")
    option_model_id = fields.Many2one('ir.model', string="Source Model", help="Model to fetch dropdown options from.")
    option_domain = fields.Char(string="Source Domain", help="Optional domain (Python list) to filter records, e.g. [('active','=',True)].")
    option_label_field = fields.Char(string="Label Field", default='name', help="Field to display as option label (default: name).")
    option_value_field = fields.Char(string="Value Field", default='id', help="Field to store as option value (default: id).")

    def _get_select_options(self):
        """Return list of dicts: [{'value': ..., 'label': ...}, ...] for select/radio fields."""
        self.ensure_one()

        # Model-backed options
        if self.option_source == 'model' and self.option_model_id and self.option_model_id.model:
            Model = self.env[self.option_model_id.model].sudo()
            domain = []
            if self.option_domain:
                try:
                    domain = safe_eval(self.option_domain, {}) or []
                except Exception:
                    domain = []
            recs = Model.search(domain, order=self.option_label_field or 'name')
            label_f = (self.option_label_field or 'name')
            value_f = (self.option_value_field or 'id')
            out = []
            for r in recs:
                try:
                    label = r[label_f] if label_f in r._fields else (r.display_name)
                except Exception:
                    label = r.display_name
                try:
                    value = r[value_f] if value_f in r._fields else r.id
                except Exception:
                    value = r.id
                out.append({'value': value, 'label': label})
            return out

        # Manual options (one per line)
        out = []
        if self.option_values:
            for line in self.option_values.split('
'):
                opt = (line or '').strip()
                if opt:
                    out.append({'value': opt, 'label': opt})
        return out


    properties = fields.Json(string="Field Configuration")

    email_hover_text = fields.Char("Email Hover Text", help="Tooltip text for email field")
    email_validation_message = fields.Char("Custom Validation Message", help="Custom error message for invalid emails")


    email_enable_domain_restriction = fields.Boolean("Enable Domain Restriction")
    email_domain_restriction_type = fields.Selection([
        ('include', 'Allow Only'),
        ('exclude', 'Block')
    ], string="Domain Restriction Type")
    email_allowed_domains = fields.Text("Domains List")
    email_domain_validation_message = fields.Char("Domain Validation Message")

    checkbox_options = fields.Text("Checkbox Options (one per line)", help="Enter one option per line for checkboxes.")
    checkbox_layout = fields.Selection([
        ('vertical', 'Vertical'),
        ('horizontal', 'Horizontal'),
        ('inline', 'Inline')
    ], string="Checkbox Layout", default='vertical', help="Choose how checkboxes are arranged.")

    date_min_date = fields.Date("Min Date", help="Earliest date that can be selected")
    date_max_date = fields.Date("Max Date", help="Latest date that can be selected")
    date_format = fields.Selection([
        ('yyyy-mm-dd', 'YYYY-MM-DD'),
        ('dd/mm/yyyy', 'DD/MM/YYYY'),
        ('mm/dd/yyyy', 'MM/DD/YYYY')
    ], string="Date Format", default='yyyy-mm-dd', help="Select the date display format.")

    time_format = fields.Selection([
        ('12', '12 Hour (AM/PM)'),
        ('24', '24 Hour')
    ], string="Time Format", default='24', help="Choose 12-hour or 24-hour format.")
    time_step = fields.Integer("Time Step (minutes)", default=15, help="Set the interval between time options.")

    month_format = fields.Selection([
        ('yyyy-mm', 'YYYY-MM'),
        ('mm/yyyy', 'MM/YYYY')
    ], string="Month Format", default='yyyy-mm',  help="Select the month display format.")

    year_min = fields.Integer("Min Year", help="Earliest selectable year.")
    year_max = fields.Integer("Max Year", help="Latest selectable year.")

    rating_max_stars = fields.Integer("Max Stars", default=5, help="Maximum number of stars/rating points")
    rating_style = fields.Selection([
        ('stars', 'Stars'),
        ('hearts', 'Hearts'),
        ('thumbs', 'Thumbs'),
        ('numbers', 'Numbers')
    ], string="Rating Style", default='stars', help="Select the style for rating display.")
    rating_allow_half = fields.Boolean("Allow Half Ratings", default=False, help="Enable half-point ratings (e.g., 4.5).")

    # ! New implementations thursday 18/09

    url_allow_external = fields.Boolean("Allow External URLs", default=True, help="Permit links to external websites.")
    url_required_protocol = fields.Selection([
        ('any', 'Any Protocol'),
        ('https', 'HTTPS Only'),
        ('http_https', 'HTTP/HTTPS Only')
    ], string="Required Protocol", default='any', help="Restrict allowed URL protocols.")
    url_open_new_tab = fields.Boolean("Open in New Tab", default=True, help="Open URLs in a new browser tab.")
    url_validation_message = fields.Char("URL Validation Message", help="Custom error message for invalid URLs.")

    address_enable_street = fields.Boolean("Enable Street Address", default=True, help="Show street address field.")
    address_enable_city = fields.Boolean("Enable City", default=True, help="Show city field.")
    address_enable_state = fields.Boolean("Enable State/Province", default=True, help="Show state/province field.")
    address_enable_zip = fields.Boolean("Enable ZIP/Postal Code", default=True, help="Show ZIP/postal code field.")
    address_enable_country = fields.Boolean("Enable Country", default=True, help="Show country field.")
    address_default_country = fields.Many2one('res.country', string="Default Country", help="Default country shown in the form.")
    address_required_fields = fields.Char("Required Address Fields", help="Comma-separated: street,city,state,zip,country")

    date_default_value = fields.Selection([
        ('none', 'No Default'),
        ('today', 'Today'),
        ('custom', 'Custom Date'),
        ('calculated', 'Calculated Date')
    ], string="Default Date", default='none')
    date_custom_default = fields.Date("Custom Default Date", help="Default date to pre-fill in the field")
    date_calculation_days = fields.Integer("Days from Today", help="Positive for future, negative for past")
    date_domain_restriction = fields.Char("Domain Restriction", help="e.g., @company.com")

    time_default_value = fields.Selection([
        ('none', 'No Default'),
        ('now', 'Current Time'),
        ('custom', 'Custom Time'),
        ('business_start', 'Business Hours Start')
    ], string="Default Time", default='none')
    time_custom_default = fields.Float("Custom Default Time (Hours)", help="e.g., 9.5 for 9:30 AM")

    month_default_value = fields.Selection([
        ('none', 'No Default'),
        ('current', 'Current Month'),
        ('fiscal_start', 'Fiscal Year Start'),
        ('custom', 'Custom Month')
    ], string="Default Month", default='none')
    month_custom_default = fields.Selection([
        ('01', 'January'), ('02', 'February'), ('03', 'March'),
        ('04', 'April'), ('05', 'May'), ('06', 'June'),
        ('07', 'July'), ('08', 'August'), ('09', 'September'),
        ('10', 'October'), ('11', 'November'), ('12', 'December')
    ], string="Custom Default Month")

    rating_allow_clear = fields.Boolean("Allow Clear/Reset", default=True)
    rating_tooltips = fields.Text("Rating Tooltips", help="Tooltip text for each rating level, one per line")
    rating_labels = fields.Text("Rating Labels", help="Labels for ratings (e.g., Poor|Fair|Good|Great|Excellent)")

    textarea_word_limit = fields.Integer("Word Limit", help="Maximum number of words allowed")
    textarea_show_counter = fields.Boolean("Show Character/Word Counter", default=True)

    select_hover_text = fields.Char("Select Hover Text", help="Tooltip text for select field")
    radio_hover_text = fields.Char("Radio Hover Text", help="Tooltip text for radio field")  # For radio too

    month_default_value = fields.Selection([
        ('none', 'No Default'),
        ('current', 'Current Month'),
        ('custom', 'Custom Month'),
        ('relative', 'Relative to Current Month')
    ], string="Default Month Value", default='none')

    month_custom_month = fields.Selection([
        ('01', 'January'), ('02', 'February'), ('03', 'March'),
        ('04', 'April'), ('05', 'May'), ('06', 'June'),
        ('07', 'July'), ('08', 'August'), ('09', 'September'),
        ('10', 'October'), ('11', 'November'), ('12', 'December')
    ], string="Custom Default Month")

    month_custom_year = fields.Integer("Custom Default Year")
    month_relative_months = fields.Integer("Relative Months")

    month_enable_min = fields.Boolean("Enable Min Month")
    month_min_year = fields.Integer("Min Month Year")
    month_min_month = fields.Selection([
        ('01', 'January'), ('02', 'February'), ('03', 'March'),
        ('04', 'April'), ('05', 'May'), ('06', 'June'),
        ('07', 'July'), ('08', 'August'), ('09', 'September'),
        ('10', 'October'), ('11', 'November'), ('12', 'December')
    ], string="Min Month")

    month_enable_max = fields.Boolean("Enable Max Month")
    month_max_year = fields.Integer("Max Month Year")
    month_max_month = fields.Selection([
        ('01', 'January'), ('02', 'February'), ('03', 'March'),
        ('04', 'April'), ('05', 'May'), ('06', 'June'),
        ('07', 'July'), ('08', 'August'), ('09', 'September'),
        ('10', 'October'), ('11', 'November'), ('12', 'December')
    ], string="Max Month")

    month_show_names = fields.Boolean("Show Month Names", default=True)
    month_restrict_future = fields.Boolean("Restrict Future Months")
    month_restrict_past = fields.Boolean("Restrict Past Months")

    time_step = fields.Selection([
        ('1', '1 minute'),
        ('5', '5 minutes'), 
        ('15', '15 minutes'),
        ('30', '30 minutes'),
        ('60', '1 hour')
    ], string="Time Step", default='15')

    time_enable_min = fields.Boolean("Enable Min Time")
    time_min_hour = fields.Integer("Min Hour")
    time_min_minute = fields.Integer("Min Minute")
    time_enable_max = fields.Boolean("Enable Max Time")
    time_max_hour = fields.Integer("Max Hour", default=23)
    time_max_minute = fields.Integer("Max Minute", default=59)
    time_restrict_business = fields.Boolean("Restrict Business Hours")
    time_business_start = fields.Integer("Business Start Hour", default=9)
    time_business_end = fields.Integer("Business End Hour", default=17)


    time_default_value = fields.Selection([
        ('none', 'No Default'),
        ('current', 'Current Time'),
        ('custom', 'Custom Time')
    ], string="Default Time Value", default='none')

    time_custom_hour = fields.Integer("Custom Hour", default=9)
    time_custom_minute = fields.Integer("Custom Minute", default=0)

    # ! Password fields 
    password_min_length = fields.Integer("Min Password Length", default=8)
    password_max_length = fields.Integer("Max Password Length", default=128)
    password_require_uppercase = fields.Boolean("Require Uppercase Letter", default=True)
    password_require_lowercase = fields.Boolean("Require Lowercase Letter", default=True)
    password_require_number = fields.Boolean("Require Number", default=True)
    password_require_special = fields.Boolean("Require Special Character", default=False)
    password_show_strength = fields.Boolean("Show Password Strength Indicator", default=True)
    password_show_toggle = fields.Boolean("Show Hide/Show Toggle", default=True)
    password_validation_message = fields.Char("Custom Validation Message")

    # ! File upload fields
    file_max_size = fields.Integer("Max File Size (MB)", default=5, help="Maximum file size in megabytes")
    file_allowed_extensions = fields.Char("Allowed File Extensions", 
        help="Comma-separated (e.g., pdf,doc,docx,jpg,png)")
    file_multiple = fields.Boolean("Allow Multiple Files", default=False)
    file_show_preview = fields.Boolean("Show File Preview", default=True)
    file_validation_message = fields.Char("Custom Validation Message")
        
    
    captcha_site_key = fields.Char("CAPTCHA Site Key", help="Google reCAPTCHA Site Key")
    captcha_secret_key = fields.Char("CAPTCHA Secret Key", help="Google reCAPTCHA Secret Key")
    captcha_theme = fields.Selection([
        ('light', 'Light'),
        ('dark', 'Dark')
    ], string="CAPTCHA Theme", default='light', help="Theme for reCAPTCHA widget")
    captcha_size = fields.Selection([
        ('normal', 'Normal'),
        ('compact', 'Compact')
    ], string="CAPTCHA Size", default='normal', help="Size for reCAPTCHA widget")

    captcha_version = fields.Selection([
        ('v2_checkbox', 'reCAPTCHA v2 - Checkbox'),
        ('v2_invisible', 'reCAPTCHA v2 - Invisible'),
        ('v3', 'reCAPTCHA v3')
    ], string="CAPTCHA Version", default='v2_checkbox')


    @api.model_create_multi
    def create(self, vals_list):
        """Log field creation"""
        records = super().create(vals_list)
        for record in records:
            if record.form_id:
                record.form_id.message_post(
                    body=f"New field '{record.label}' ({record.field_type}) added to form",
                    message_type='notification'
                )
        return records

    def unlink(self):
        """Log field deletion"""
        for record in self:
            if record.form_id:
                record.form_id.message_post(
                    body=f"Field '{record.label}' removed from form",
                    message_type='notification'
                )
        return super().unlink()

    def open_phone_field_wizard(self):
        return self._open_field_wizard('phone.field.config.wizard', _('Configure Phone Field'))
    
    def open_text_field_wizard(self):
        return self._open_field_wizard('text.field.config.wizard', _('Configure Text Fields'))
    
    def open_number_field_wizard(self):
        return self._open_field_wizard('number.field.config.wizard', _('Configure Number Field'))
    
    def open_textarea_field_wizard(self):
        return self._open_field_wizard('textarea.field.config.wizard', _('Configure Textarea Field'))
    
    def open_select_field_wizard(self):
        return self._open_field_wizard('select.field.config.wizard', _('Configure Select Field'))

    def open_email_field_wizard(self):
        return self._open_field_wizard('email.field.config.wizard', _('Configure Email Field'))

    def open_checkbox_field_wizard(self):
        return self._open_field_wizard('checkbox.field.config.wizard', _('Configure Checkbox Field'))

    def open_date_field_wizard(self):
        return self._open_field_wizard('date.field.config.wizard', _('Configure Date Field'))

    def open_time_field_wizard(self):
        return self._open_field_wizard('time.field.config.wizard', _('Configure Time Field'))

    def open_month_field_wizard(self):
        return self._open_field_wizard('month.field.config.wizard', _('Configure Month Field'))

    def open_year_field_wizard(self):
        return self._open_field_wizard('year.field.config.wizard', _('Configure Year Field'))

    def open_rating_field_wizard(self):
        return self._open_field_wizard('rating.field.config.wizard', _('Configure Rating Field'))

    def _open_field_wizard(self, wizard_model, title):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': title,
            'res_model': wizard_model,
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_field_id': self.id}
        }
    def open_password_field_wizard(self):
        return self._open_field_wizard('password.field.config.wizard', _('Configure Password Field'))

    def open_file_field_wizard(self):
        return self._open_field_wizard('file.field.config.wizard', _('Configure File Upload Field'))

    def open_url_field_wizard(self):
        return self._open_field_wizard('url.field.config.wizard', _('Configure URL Field'))

    def open_address_field_wizard(self):
        return self._open_field_wizard('address.field.config.wizard', _('Configure Address Field'))

    def open_captcha_field_wizard(self):
        self.ensure_one()
        return {
            'name': _('Configure CAPTCHA Field'),
            'type': 'ir.actions.act_window',
            'res_model': 'captcha.field.config.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_field_id': self.id}
        }

    def validate_captcha(self, response):
        _logger.info('=== CAPTCHA Validation Debug ===')
        _logger.info(f'Field ID: {self.id}')
        _logger.info(f'Site Key: {self.captcha_site_key[:10]}... (hidden)')
        _logger.info(f'Secret Key exists: {bool(self.captcha_secret_key)}')
        _logger.info(f'Response token: {response[:20]}... (truncated)')
        
        secret_key = self.captcha_secret_key
        url = "https://www.google.com/recaptcha/api/siteverify"
        data = {
            'secret': secret_key,
            'response': response
        }
        
        try:
            res = requests.post(url, data=data, timeout=10)
            result = res.json()
            _logger.info(f'reCAPTCHA API Response: {result}')
            return result.get('success', False)
        except Exception as e:
            _logger.error(f'CAPTCHA validation error: {str(e)}')
            return False
