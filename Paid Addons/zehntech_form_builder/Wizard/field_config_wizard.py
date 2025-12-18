# Wizard/field_config_wizard.py
from odoo import models, fields, api

class PhoneFieldConfigWizard(models.TransientModel):
    _name = 'phone.field.config.wizard'
    _description = 'Phone Field Configuration Wizard'

    field_id = fields.Many2one('form.builder.field', string="Field", required=True)
    hover_text = fields.Char("Hover Text")
    min_length = fields.Integer("Min Length", default=10)
    max_length = fields.Integer("Max Length", default=15)
    country_code = fields.Many2one('res.country', string="Country Code")
    show_country_selector = fields.Boolean("Show Country Code Selector", default=True)

    @api.model
    def default_get(self, fields_list):
        defaults = super().default_get(fields_list)
        field_id = self.env.context.get('default_field_id')
        if field_id:
            field = self.env['form.builder.field'].browse(field_id)
            defaults.update({
                'hover_text': field.phone_hover_text,
                'min_length': field.phone_min_length or 10,
                'max_length': field.phone_max_length or 15,
                'show_country_selector': field.phone_show_country_selector,
            })
        return defaults

    def action_save_phone_config(self):
        self.field_id.write({
            'phone_min_length': self.min_length,
            'phone_max_length': self.max_length,
            'phone_show_country_selector': self.show_country_selector,
            'phone_hover_text': self.hover_text,
        })
        return {'type': 'ir.actions.act_window_close'}


class TextFieldConfigWizard(models.TransientModel):
    _name = 'text.field.config.wizard'
    _description = 'Text Field Configuration Wizard'

    field_id = fields.Many2one('form.builder.field', string="Field", required=True)
    min_length = fields.Integer("Min Length")
    max_length = fields.Integer("Max Length")
    pattern = fields.Char("Pattern (Regex)", help="e.g., [A-Za-z]+ for letters only")

    @api.model
    def default_get(self, fields_list):
        defaults = super().default_get(fields_list)
        field_id = self.env.context.get('default_field_id')
        if field_id:
            field = self.env['form.builder.field'].browse(field_id)
            defaults.update({
                'min_length': field.text_min_length,
                'max_length': field.text_max_length,
                'pattern': field.text_pattern,
            })
        return defaults

    def action_save_text_config(self):
        self.field_id.write({
            'text_min_length': self.min_length,
            'text_max_length': self.max_length,
            'text_pattern': self.pattern,
        })
        return {'type': 'ir.actions.act_window_close'}


class NumberFieldConfigWizard(models.TransientModel):
    _name = 'number.field.config.wizard'
    _description = 'Number Field Configuration Wizard'

    field_id = fields.Many2one('form.builder.field', string="Field", required=True)
    min_value = fields.Float("Min Value")
    max_value = fields.Float("Max Value")
    step = fields.Float("Step", default=1)

    @api.model
    def default_get(self, fields_list):
        defaults = super().default_get(fields_list)
        field_id = self.env.context.get('default_field_id')
        if field_id:
            field = self.env['form.builder.field'].browse(field_id)
            defaults.update({
                'min_value': field.number_min_value,
                'max_value': field.number_max_value,
                'step': field.number_step or 1,
            })
        return defaults

    def action_save_number_config(self):
        self.field_id.write({
            'number_min_value': self.min_value,
            'number_max_value': self.max_value,
            'number_step': self.step,
        })
        return {'type': 'ir.actions.act_window_close'}


class TextareaFieldConfigWizard(models.TransientModel):
    _name = 'textarea.field.config.wizard'
    _description = 'Textarea Field Configuration Wizard'

    field_id = fields.Many2one('form.builder.field', string="Field", required=True)
    rows = fields.Integer("Number of Rows", default=3)
    max_chars = fields.Integer("Max Characters")

    @api.model
    def default_get(self, fields_list):
        defaults = super().default_get(fields_list)
        field_id = self.env.context.get('default_field_id')
        if field_id:
            field = self.env['form.builder.field'].browse(field_id)
            defaults.update({
                'rows': field.textarea_rows or 3,
                'max_chars': field.textarea_max_chars,
            })
        return defaults

    def action_save_textarea_config(self):
        self.field_id.write({
            'textarea_rows': self.rows,
            'textarea_max_chars': self.max_chars,
        })
        return {'type': 'ir.actions.act_window_close'}


class SelectFieldConfigWizard(models.TransientModel):
    _name = 'select.field.config.wizard'
    _description = 'Select Field Configuration Wizard'

    field_id = fields.Many2one('form.builder.field', string="Field", required=True)
    option_values = fields.Text("Options", help="Enter each option on a new line")
    hover_text = fields.Char("Hover Text", help="Tooltip text displayed on hover")

    @api.model
    def default_get(self, fields_list):
        defaults = super().default_get(fields_list)
        field_id = self.env.context.get('default_field_id')
        if field_id:
            field = self.env['form.builder.field'].browse(field_id)
            defaults.update({
                'option_values': field.option_values,
                'hover_text': field.select_hover_text,
            })
        return defaults

    def action_save_select_config(self):
        self.field_id.write({
            'option_values': self.option_values,
            'select_hover_text': self.hover_text,
        })
        return {'type': 'ir.actions.act_window_close'}


class EmailFieldConfigWizard(models.TransientModel):
    _name = 'email.field.config.wizard'
    _description = 'Email Field Configuration Wizard'

    field_id = fields.Many2one('form.builder.field', string="Field", required=True)
    hover_text = fields.Char("Hover Text")
    validation_message = fields.Char("Description")

    enable_domain_restriction = fields.Boolean("Enable Domain Restriction", default=False)
    domain_restriction_type = fields.Selection([
        ('include', 'Allow Only These Domains'),
        ('exclude', 'Block These Domains')
    ], string="Restriction Type", default='include')
    allowed_domains = fields.Text("Allowed/Blocked Domains", 
        help="One domain per line (e.g., gmail.com, outlook.com)")
    domain_validation_message = fields.Char("Domain Validation Message",
        default="Email domain is not allowed")

    @api.model
    def default_get(self, fields_list):
        defaults = super().default_get(fields_list)
        field_id = self.env.context.get('default_field_id')
        if field_id:
            field = self.env['form.builder.field'].browse(field_id)
            defaults.update({
                'hover_text': field.email_hover_text,
                'validation_message': field.email_validation_message,
                'enable_domain_restriction': field.email_enable_domain_restriction,
                'domain_restriction_type': field.email_domain_restriction_type,
                'allowed_domains': field.email_allowed_domains,
                'domain_validation_message': field.email_domain_validation_message,
            })
        return defaults

    def action_save_email_config(self):
        self.field_id.write({
            'email_hover_text': self.hover_text,
            'email_validation_message': self.validation_message,
            'email_enable_domain_restriction': self.enable_domain_restriction,
            'email_domain_restriction_type': self.domain_restriction_type,
            'email_allowed_domains': self.allowed_domains,
            'email_domain_validation_message': self.domain_validation_message,
        })
        return {'type': 'ir.actions.act_window_close'}


class CheckboxFieldConfigWizard(models.TransientModel):
    _name = 'checkbox.field.config.wizard'
    _description = 'Checkbox Field Configuration Wizard'

    field_id = fields.Many2one('form.builder.field', string="Field", required=True)
    checkbox_options = fields.Text("Options", help="Enter each option on a new line")
    layout = fields.Selection([
        ('vertical', 'Vertical'),
        ('horizontal', 'Horizontal'),
    ], string="Layout", default='vertical')

    @api.model
    def default_get(self, fields_list):
        defaults = super().default_get(fields_list)
        field_id = self.env.context.get('default_field_id')
        if field_id:
            field = self.env['form.builder.field'].browse(field_id)
            defaults.update({
                'checkbox_options': field.checkbox_options,
                'layout': field.checkbox_layout or 'vertical',
            })
        return defaults

    def action_save_checkbox_config(self):
        self.field_id.write({
            'checkbox_options': self.checkbox_options,
            'checkbox_layout': self.layout,
        })
        return {'type': 'ir.actions.act_window_close'}


class DateFieldConfigWizard(models.TransientModel):
    _name = 'date.field.config.wizard'
    _description = 'Date Field Configuration Wizard'

    field_id = fields.Many2one('form.builder.field', string="Field", required=True)
    min_date = fields.Date("Min Date")
    max_date = fields.Date("Max Date")
 

    @api.model
    def default_get(self, fields_list):
        defaults = super().default_get(fields_list)
        field_id = self.env.context.get('default_field_id')
        if field_id:
            field = self.env['form.builder.field'].browse(field_id)
            defaults.update({
                'min_date': field.date_min_date,
                'max_date': field.date_max_date,
                
            })
        return defaults

    def action_save_date_config(self):
        self.field_id.write({
            'date_min_date': self.min_date,
            'date_max_date': self.max_date,
            
        })
        return {'type': 'ir.actions.act_window_close'}


class TimeFieldConfigWizard(models.TransientModel):
    _name = 'time.field.config.wizard'
    _description = 'Time Field Configuration Wizard'

    field_id = fields.Many2one('form.builder.field', string="Field", required=True)
    
    # Only default time options
    default_time = fields.Selection([
        ('none', 'No Default'),
        ('current', 'Current Time'),
        ('custom', 'Custom Time')
    ], string="Default Time", default='none')
    
    custom_hour = fields.Integer("Custom Hour (0-23)", default=9)
    custom_minute = fields.Integer("Custom Minute (0-59)", default=0)

    @api.model
    def default_get(self, fields_list):
        defaults = super().default_get(fields_list)
        field_id = self.env.context.get('default_field_id')
        if field_id:
            field = self.env['form.builder.field'].browse(field_id)
            defaults.update({
                'default_time': field.time_default_value or 'none',
                'custom_hour': field.time_custom_hour or 9,
                'custom_minute': field.time_custom_minute or 0,
            })
        return defaults

    def action_save_time_config(self):
        self.field_id.write({
            'time_default_value': self.default_time,
            'time_custom_hour': self.custom_hour,
            'time_custom_minute': self.custom_minute,
        })
        return {'type': 'ir.actions.act_window_close'}



class YearFieldConfigWizard(models.TransientModel):
    _name = 'year.field.config.wizard'
    _description = 'Year Field Configuration Wizard'

    field_id = fields.Many2one('form.builder.field', string="Field", required=True)
    min_year = fields.Integer("Min Year")
    max_year = fields.Integer("Max Year")

    @api.model
    def default_get(self, fields_list):
        defaults = super().default_get(fields_list)
        field_id = self.env.context.get('default_field_id')
        if field_id:
            field = self.env['form.builder.field'].browse(field_id)
            defaults.update({
                'min_year': field.year_min,
                'max_year': field.year_max,
            })
        return defaults

    def action_save_year_config(self):
        self.field_id.write({
            'year_min': self.min_year,
            'year_max': self.max_year,
        })
        return {'type': 'ir.actions.act_window_close'}


class RatingFieldConfigWizard(models.TransientModel):
    _name = 'rating.field.config.wizard'
    _description = 'Rating Field Configuration Wizard'

    field_id = fields.Many2one('form.builder.field', string="Field", required=True)
    max_stars = fields.Integer("Max Stars/Points", default=5)
    style = fields.Selection([
        ('stars', 'Stars'),
        ('hearts', 'Hearts'),
        ('thumbs', 'Thumbs'),
        ('numbers', 'Numbers')
    ], string="Rating Style", default='stars')
    allow_clear = fields.Boolean("Allow Clear/Reset", default=True)
    tooltips = fields.Text("Rating Tooltips", help="One per line for each rating level")
    labels = fields.Text("Rating Labels", help="Labels for ratings (e.g., Poor|Fair|Good|Great|Excellent)")

    @api.model
    def default_get(self, fields_list):
        defaults = super().default_get(fields_list)
        field_id = self.env.context.get('default_field_id')
        if field_id:
            field = self.env['form.builder.field'].browse(field_id)
            defaults.update({
                'max_stars': field.rating_max_stars or 5,
                'style': field.rating_style or 'stars',
                'allow_clear': field.rating_allow_clear,
                'tooltips': field.rating_tooltips,
                'labels': field.rating_labels,
            })
        return defaults

    def action_save_rating_config(self):
        self.field_id.write({
            'rating_max_stars': self.max_stars,
            'rating_style': self.style,
            'rating_allow_clear': self.allow_clear,
            'rating_tooltips': self.tooltips,
            'rating_labels': self.labels,
        })
        return {'type': 'ir.actions.act_window_close'}

    # Add these new wizard classes to your field_config_wizard.py file

class URLFieldConfigWizard(models.TransientModel):
    _name = 'url.field.config.wizard'
    _description = 'URL Field Configuration Wizard'

    field_id = fields.Many2one('form.builder.field', string="Field", required=True)
    allow_external = fields.Boolean("Allow External URLs", default=True)
    required_protocol = fields.Selection([
        ('any', 'Any Protocol'),
        ('https', 'HTTPS Only'),
        ('http_https', 'HTTP/HTTPS Only')
    ], string="Required Protocol", default='any')
    open_new_tab = fields.Boolean("Open in New Tab", default=True)
    validation_message = fields.Char("Description")

    @api.model
    def default_get(self, fields_list):
        defaults = super().default_get(fields_list)
        field_id = self.env.context.get('default_field_id')
        if field_id:
            field = self.env['form.builder.field'].browse(field_id)
            defaults.update({
                'allow_external': field.url_allow_external,
                'required_protocol': field.url_required_protocol or 'any',
                'open_new_tab': field.url_open_new_tab,
                'validation_message': field.url_validation_message,
            })
        return defaults

    def action_save_url_config(self):
        self.field_id.write({
            'url_allow_external': self.allow_external,
            'url_required_protocol': self.required_protocol,
            'url_open_new_tab': self.open_new_tab,
            'url_validation_message': self.validation_message,
        })
        return {'type': 'ir.actions.act_window_close'}


class AddressFieldConfigWizard(models.TransientModel):
    _name = 'address.field.config.wizard'
    _description = 'Address Field Configuration Wizard'

    field_id = fields.Many2one('form.builder.field', string="Field", required=True)
    enable_street = fields.Boolean("Enable Street Address", default=True)
    enable_city = fields.Boolean("Enable City", default=True)
    enable_state = fields.Boolean("Enable State/Province", default=True)
    enable_zip = fields.Boolean("Enable ZIP/Postal Code", default=True)
    enable_country = fields.Boolean("Enable Country", default=True)
    default_country = fields.Many2one('res.country', string="Default Country")
    required_fields = fields.Char("Required Address Fields", help="Comma-separated: street,city,state,zip,country")

    @api.model
    def default_get(self, fields_list):
        defaults = super().default_get(fields_list)
        field_id = self.env.context.get('default_field_id')
        if field_id:
            field = self.env['form.builder.field'].browse(field_id)
            defaults.update({
                'enable_street': field.address_enable_street,
                'enable_city': field.address_enable_city,
                'enable_state': field.address_enable_state,
                'enable_zip': field.address_enable_zip,
                'enable_country': field.address_enable_country,
                'default_country': field.address_default_country.id if field.address_default_country else False,
                'required_fields': field.address_required_fields,
            })
        return defaults

    def action_save_address_config(self):
        self.field_id.write({
            'address_enable_street': self.enable_street,
            'address_enable_city': self.enable_city,
            'address_enable_state': self.enable_state,
            'address_enable_zip': self.enable_zip,
            'address_enable_country': self.enable_country,
            'address_default_country': self.default_country.id if self.default_country else False,
            'address_required_fields': self.required_fields,
        })
        return {'type': 'ir.actions.act_window_close'}

class MonthFieldConfigWizard(models.TransientModel):
    _name = 'month.field.config.wizard'
    _description = 'Month Field Configuration Wizard'

    field_id = fields.Many2one('form.builder.field', string="Field", required=True)
    
    # Default value options
    default_value = fields.Selection([
        ('none', 'No Default'),
        ('current', 'Current Month'),
        ('custom', 'Custom Month'),
        ('relative', 'Relative to Current Month')
    ], string="Default Value", default='none')
    
    custom_month = fields.Selection([
        ('01', 'January'), ('02', 'February'), ('03', 'March'),
        ('04', 'April'), ('05', 'May'), ('06', 'June'),
        ('07', 'July'), ('08', 'August'), ('09', 'September'),
        ('10', 'October'), ('11', 'November'), ('12', 'December')
    ], string="Custom Default Month")
    
    custom_year = fields.Integer("Custom Year", default=lambda self: fields.Date.today().year)
    
    relative_months = fields.Integer("Months from Current", help="Positive for future, negative for past", default=0)
    
    # Range restrictions
    enable_min_month = fields.Boolean("Enable Minimum Month", default=False)
    min_month_year = fields.Integer("Min Year", default=lambda self: fields.Date.today().year - 10)
    min_month_month = fields.Selection([
        ('01', 'January'), ('02', 'February'), ('03', 'March'),
        ('04', 'April'), ('05', 'May'), ('06', 'June'),
        ('07', 'July'), ('08', 'August'), ('09', 'September'),
        ('10', 'October'), ('11', 'November'), ('12', 'December')
    ], string="Min Month", default='01')
    
    enable_max_month = fields.Boolean("Enable Maximum Month", default=False)
    max_month_year = fields.Integer("Max Year", default=lambda self: fields.Date.today().year + 10)
    max_month_month = fields.Selection([
        ('01', 'January'), ('02', 'February'), ('03', 'March'),
        ('04', 'April'), ('05', 'May'), ('06', 'June'),
        ('07', 'July'), ('08', 'August'), ('09', 'September'),
        ('10', 'October'), ('11', 'November'), ('12', 'December')
    ], string="Max Month", default='12')
    
    # Display options
    show_month_names = fields.Boolean("Show Month Names", default=True, help="Display 'September 2025' instead of '2025-09'")
    
    # Validation options
    restrict_future = fields.Boolean("Restrict Future Months", default=False)
    restrict_past = fields.Boolean("Restrict Past Months", default=False)
    
    # Help text
    help_text = fields.Char("Help Text", help="Additional help text displayed below the field")

    @api.model
    def default_get(self, fields_list):
        defaults = super().default_get(fields_list)
        field_id = self.env.context.get('default_field_id')
        if field_id:
            field = self.env['form.builder.field'].browse(field_id)
            defaults.update({
                'default_value': field.month_default_value or 'none',
                'custom_month': field.month_custom_month,
                'custom_year': field.month_custom_year or fields.Date.today().year,
                'relative_months': field.month_relative_months or 0,
                'enable_min_month': field.month_enable_min,
                'min_month_year': field.month_min_year or fields.Date.today().year - 10,
                'min_month_month': field.month_min_month or '01',
                'enable_max_month': field.month_enable_max,
                'max_month_year': field.month_max_year or fields.Date.today().year + 10,
                'max_month_month': field.month_max_month or '12',
                'show_month_names': field.month_show_names,
                'restrict_future': field.month_restrict_future,
                'restrict_past': field.month_restrict_past,
                'help_text': field.help_text,
            })
        return defaults

    def action_save_month_config(self):
        values = {
            'month_default_value': self.default_value,
            'month_custom_month': self.custom_month,
            'month_custom_year': self.custom_year,
            'month_relative_months': self.relative_months,
            'month_enable_min': self.enable_min_month,
            'month_min_year': self.min_month_year,
            'month_min_month': self.min_month_month,
            'month_enable_max': self.enable_max_month,
            'month_max_year': self.max_month_year,
            'month_max_month': self.max_month_month,
            'month_show_names': self.show_month_names,
            'month_restrict_future': self.restrict_future,
            'month_restrict_past': self.restrict_past,
            'help_text': self.help_text,
        }
        self.field_id.write(values)
        return {'type': 'ir.actions.act_window_close'}


class PasswordFieldConfigWizard(models.TransientModel):
    _name = 'password.field.config.wizard'
    _description = 'Password Field Configuration Wizard'

    field_id = fields.Many2one('form.builder.field', string="Field", required=True)
    min_length = fields.Integer("Min Length", default=8)
    max_length = fields.Integer("Max Length", default=128)
    require_uppercase = fields.Boolean("Require Uppercase", default=True)
    require_lowercase = fields.Boolean("Require Lowercase", default=True)
    require_number = fields.Boolean("Require Number", default=True)
    require_special = fields.Boolean("Require Special Character", default=False)
    show_strength = fields.Boolean("Show Strength Indicator", default=True)
    show_toggle = fields.Boolean("Show Hide/Show Toggle", default=True)
    validation_message = fields.Char("Description")

    @api.model
    def default_get(self, fields_list):
        defaults = super().default_get(fields_list)
        field_id = self.env.context.get('default_field_id')
        if field_id:
            field = self.env['form.builder.field'].browse(field_id)
            defaults.update({
                'min_length': field.password_min_length or 8,
                'max_length': field.password_max_length or 128,
                'require_uppercase': field.password_require_uppercase,
                'require_lowercase': field.password_require_lowercase,
                'require_number': field.password_require_number,
                'require_special': field.password_require_special,
                'show_strength': field.password_show_strength,
                'show_toggle': field.password_show_toggle,
                'validation_message': field.password_validation_message,
            })
        return defaults

    def action_save_password_config(self):
        self.field_id.write({
            'password_min_length': self.min_length,
            'password_max_length': self.max_length,
            'password_require_uppercase': self.require_uppercase,
            'password_require_lowercase': self.require_lowercase,
            'password_require_number': self.require_number,
            'password_require_special': self.require_special,
            'password_show_strength': self.show_strength,
            'password_show_toggle': self.show_toggle,
            'password_validation_message': self.validation_message,
        })
        return {'type': 'ir.actions.act_window_close'}

class FileFieldConfigWizard(models.TransientModel):
    _name = 'file.field.config.wizard'
    _description = 'File Upload Configuration Wizard'

    field_id = fields.Many2one('form.builder.field', string="Field", required=True)
    max_size = fields.Integer("Max File Size (MB)", default=5)
    allowed_extensions = fields.Char("Allowed Extensions", 
        help="pdf,doc,docx,jpg,png,xlsx,csv")
    multiple = fields.Boolean("Allow Multiple Files", default=False)
    show_preview = fields.Boolean("Show Preview", default=True)
    validation_message = fields.Char("Description")

    @api.model
    def default_get(self, fields_list):
        defaults = super().default_get(fields_list)
        field_id = self.env.context.get('default_field_id')
        if field_id:
            field = self.env['form.builder.field'].browse(field_id)
            defaults.update({
                'max_size': field.file_max_size or 5,
                'allowed_extensions': field.file_allowed_extensions,
                'multiple': field.file_multiple,
                'show_preview': field.file_show_preview,
                'validation_message': field.file_validation_message,
            })
        return defaults

    def action_save_file_config(self):
        self.field_id.write({
            'file_max_size': self.max_size,
            'file_allowed_extensions': self.allowed_extensions,
            'file_multiple': self.multiple,
            'file_show_preview': self.show_preview,
            'file_validation_message': self.validation_message,
        })
        return {'type': 'ir.actions.act_window_close'}



class CaptchaFieldConfigWizard(models.TransientModel):
    _name = 'captcha.field.config.wizard'
    _description = 'CAPTCHA Field Configuration Wizard'

    field_id = fields.Many2one('form.builder.field', string="Field", required=True)
    
    captcha_version = fields.Selection([
        ('v2_checkbox', 'reCAPTCHA v2 - Checkbox'),
        ('v2_invisible', 'reCAPTCHA v2 - Invisible'),
        ('v3', 'reCAPTCHA v3')
    ], string="Version", default='v2_checkbox', required=True, 
       help="Make sure your keys match this version!")
    
    site_key = fields.Char("Site Key", required=True, help="Google reCAPTCHA Site Key")
    secret_key = fields.Char("Secret Key", required=True, help="Google reCAPTCHA Secret Key")
    theme = fields.Selection([
        ('light', 'Light'),
        ('dark', 'Dark')
    ], string="Theme", default='light')
    size = fields.Selection([
        ('normal', 'Normal'),
        ('compact', 'Compact')
    ], string="Size", default='normal')

    @api.model
    def default_get(self, fields_list):
        defaults = super().default_get(fields_list)
        field_id = self.env.context.get('default_field_id')
        if field_id:
            field = self.env['form.builder.field'].browse(field_id)
            defaults.update({
                'captcha_version': field.captcha_version or 'v2_checkbox',
                'site_key': field.captcha_site_key,
                'secret_key': field.captcha_secret_key,
                'theme': field.captcha_theme or 'light',
                'size': field.captcha_size or 'normal',
            })
        return defaults

    def action_save_captcha_config(self):
        self.ensure_one()
        self.field_id.write({
            'captcha_version': self.captcha_version,
            'captcha_site_key': self.site_key,
            'captcha_secret_key': self.secret_key,
            'captcha_theme': self.theme,
            'captcha_size': self.size,
        })
        return {'type': 'ir.actions.act_window_close'}