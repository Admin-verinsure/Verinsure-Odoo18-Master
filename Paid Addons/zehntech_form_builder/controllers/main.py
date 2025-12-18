import json
from odoo import http, _
from odoo.http import request, route
import logging
import csv
from io import StringIO
import base64
from werkzeug.wrappers import Response
from datetime import datetime
import pytz

_logger = logging.getLogger(__name__)

class FormBuilderPreview(http.Controller):

    @route('/form_builder/preview/<int:form_id>', type='http', auth='user')
    def preview_form(self, form_id, **kwargs):
        form = request.env['form.builder'].sudo().browse(form_id)
        saved_styles = form.get_form_styles() if hasattr(form, 'get_form_styles') else {}
        
        return request.render('zehntech_form_builder.form_preview_template', {
            'form': form,
            'fields': form.field_ids.sorted(key=lambda f: f.sequence),
            'saved_styles': json.dumps(saved_styles),
        })

    @http.route(['/form_builder/get_styles/<int:form_id>'], type='http', auth='public', csrf=False, methods=['GET'])
    def get_form_styles(self, form_id, **kwargs):
        """Get form styles for both preview and shared forms"""
        try:
            form = request.env['form.builder'].sudo().browse(form_id)
            if not form.exists():
                return request.make_json_response({'success': False, 'error': 'Form not found'}, status=404)
            
            styles = {}
            if form.form_styles:
                try:
                    styles = json.loads(form.form_styles)
                except (ValueError, TypeError) as e:
                    _logger.error(f'Error parsing form styles for form {form_id}: {str(e)}')
                    styles = {}
            else:
                _logger.info(f'No styles found for form {form_id}')
            
            return request.make_json_response({'success': True, 'styles': styles})
        except Exception as e:
            _logger.error(f'Error getting form styles for form {form_id}: {str(e)}')
            return request.make_json_response({'success': False, 'error': 'Internal server error'}, status=500)

# ! New styles changes from here groke
    @http.route(['/form_builder/save_styles/<int:form_id>'], type='json', auth='user', methods=['POST'], csrf=False)
    def save_form_styles(self, form_id, **kwargs):
        try:
            form = request.env['form.builder'].browse(form_id)
            if not form.exists():
                return {'success': False, 'error': 'Form not found'}
            
            json_data = request.get_json_data()
            styles = json_data.get('styles', {}) if json_data else {}
            
            
            if not isinstance(styles, dict):
                return {'success': False, 'error': 'Invalid styles format'}
            
            if not styles:
                return {'success': False, 'error': 'No styles provided'}
            
            form.save_form_styles(styles)
            
            return {'success': True, 'message': 'Styles saved successfully'}
            
        except Exception as e:
            _logger.error(f'Error saving form styles for form {form_id}: {str(e)}')
            return {'success': False, 'error': f'Server error: {str(e)}'}


    # @http.route(['/form_builder/debug_styles/<int:form_id>'], type='http', auth='user', csrf=False)
    # def debug_form_styles(self, form_id, **kwargs):
    #     """Debug route to check what's in database"""
    #     form = request.env['form.builder'].sudo().browse(form_id)
    #     if not form.exists():
    #         return "Form not found"
        
    #     request.cr.execute("SELECT form_styles, custom_styles FROM form_builder WHERE id = %s", (form_id,))
    #     result = request.cr.fetchone()
        
    #     debug_info = f"""
    #     <h3>Debug Info for Form {form_id}</h3>
    #     <p><strong>Via ORM - form_styles:</strong> {form.form_styles}</p>
    #     <p><strong>Via ORM - custom_styles:</strong> {form.custom_styles}</p>
    #     <p><strong>Via SQL - form_styles:</strong> {result[0] if result else 'No result'}</p>
    #     <p><strong>Via SQL - custom_styles:</strong> {result[1] if result else 'No result'}</p>
    #     <p><strong>Form exists:</strong> {form.exists()}</p>
    #     <p><strong>Form name:</strong> {form.name}</p>
    #     """
        
    #     return debug_info

    def _convert_styles_to_css(self, styles, form_id):
        """Convert JavaScript styles object to CSS"""
        css_rules = []
        form_class = f".form-id-{form_id}"
        
        if 'page-bg-color' in styles:
            css_rules.append(f"{form_class}.form-preview-wrapper {{ background: linear-gradient(135deg, {styles['page-bg-color']}, {styles['page-bg-color']}20) !important; }}")
        
        if 'form-bg-color' in styles:
            css_rules.append(f"{form_class} .form-preview-card {{ background-color: {styles['form-bg-color']} !important; }}")
        
        if 'font-family' in styles:
            css_rules.append(f"{form_class} .form-preview-card {{ font-family: {styles['font-family']} !important; }}")
        
        if 'font-size' in styles:
            css_rules.append(f"{form_class} .form-preview-card {{ font-size: {styles['font-size']} !important; }}")
        
        if 'input-bg-color' in styles:
            css_rules.append(f"{form_class} .form-preview-card .form-control {{ background-color: {styles['input-bg-color']} !important; }}")
        
        if 'input-border-color' in styles:
            css_rules.append(f"{form_class} .form-preview-card .form-control {{ border-color: {styles['input-border-color']} !important; }}")
        
        if 'input-border-radius' in styles:
            css_rules.append(f"{form_class} .form-preview-card .form-control {{ border-radius: {styles['input-border-radius']} !important; }}")
        
        if 'label-color' in styles:
            css_rules.append(f"{form_class} .form-preview-card .form-label {{ color: {styles['label-color']} !important; }}")
        
        if 'label-weight' in styles:
            css_rules.append(f"{form_class} .form-preview-card .form-label {{ font-weight: {styles['label-weight']} !important; }}")
        
        if 'button-bg-color' in styles:
            css_rules.append(f"{form_class} .form-preview-card .form-submit-button{{ background-color: {styles['button-bg-color']} !important; border-color: {styles['button-bg-color']} !important; }}")
        
        if 'button-border-radius' in styles:
            css_rules.append(f"{form_class} .form-preview-card .btn-primary {{ border-radius: {styles['button-border-radius']} !important; }}")
        
        if 'field-spacing' in styles:
            css_rules.append(f"{form_class} .form-preview-card .form-field {{ margin-bottom: {styles['field-spacing']} !important; }}")
        
        if 'form-padding' in styles:
            css_rules.append(f"{form_class} .form-preview-card {{ padding: {styles['form-padding']} !important; }}")
        if 'title-color' in styles:
            css_rules.append(f"{form_class} .form-header h2 {{ color: {styles['title-color']} !important; }}")
        
        return '\n'.join(css_rules)

    @http.route('/form_builder/update_sequence', type='json', auth='user', csrf=False)
    def update_sequence(self, sequence_data=None, **kwargs):
        if sequence_data:
            for item in sequence_data:
                field = request.env['form.builder.field'].sudo().browse(item['id'])
                if field.exists():
                    field.write({'sequence': item['sequence']})
        return {'status': 'success'}


class FormPublicController(http.Controller):

    def _track_form_view(self, form, request):
        """Track form view for analytics"""
        try:
            ip_address = request.httprequest.environ.get('REMOTE_ADDR', 'Unknown')
            
            country = 'Unknown'
            
            request.env['form.view.tracker'].sudo().create({
                'form_id': form.id,
                'ip_address': ip_address,
                'country': country,
                'user_agent': request.httprequest.headers.get('User-Agent', '')
            })
            
            form.increment_view_count()
            
        except Exception as e:
            _logger.error(f'Error tracking form view: {str(e)}')


    def _get_user_language(self, **kwargs):
        """Get language from URL parameter or browser"""
        lang = kwargs.get('lang') or request.httprequest.args.get('lang')
        
        if not lang:
            accept_language = request.httprequest.headers.get('Accept-Language', '')
            browser_lang = accept_language.split(',')[0].split('-')[0] if accept_language else 'en'
            lang = browser_lang
        
        supported_langs = {
            'en': 'en_US',
            'ja': 'ja_JP', 
            'fr': 'fr_FR',
            'de': 'de_DE',
            'es': 'es_ES'
        }
        
        return supported_langs.get(lang, 'en_US')

    @http.route(['/form_builder/shared/<string:token>'], type='http', auth="public", website=True, csrf=False)
    def shared_form_view(self, token, **kwargs):
        """Handle shared form view with token"""
        _logger.info("Accessing shared form with token: %s", token)

        user_lang = self._get_user_language(**kwargs)
        
        form = request.env['form.builder'].with_context(lang=user_lang).sudo().search([('share_token', '=', token)], limit=1)
        
        if not form:
            return request.not_found()
        
        if form.status == 'unpublished':
            return request.render('zehntech_form_builder.form_expired_template', {
                'form': form,
                'message': 'This form has expired and is no longer accepting responses.',
                'message_on_unpublish': form.message_on_unpublish or "Form expired!!"
            })
        
        if form.status != 'published':
            return request.not_found()

        if not form.is_form_available():
            return request.render('zehntech_form_builder.form_expired_template', {
                'form': form,
                'message': form.availability_message or 'This form is currently not available. Please try again later.',
                'message_on_unpublish': form.availability_message or 'Form not available'
            })

        self._track_form_view(form, request)

        return request.render('zehntech_form_builder.public_form_template', {
            'form': form,
            'fields': form.field_ids.sorted(key=lambda f: f.sequence),
            'user_lang': user_lang.split('_')[0],  # Pass 'en', 'ja', etc.
        })

    @http.route(['/form_builder/submit'], type='http', auth="public", methods=['POST'], website=True, csrf=False)
    def handle_form_submit(self, **post):
        """Handle form submission with email notifications"""
        try:
            token = post.get('token')

            lang_param = post.get('lang', 'en')

            if not token:
                return request.render('zehntech_form_builder.form_thank_you_template')

            form = request.env['form.builder'].sudo().search([('share_token', '=', token)], limit=1)
            
            if not form or form.status != 'published':
                return request.render('zehntech_form_builder.form_expired_template', {
                    'form': form,
                    'message': 'This form is no longer accepting responses.',
                    'message_on_unpublish': form.message_on_unpublish or "Form expired!!"
                })

            if not form.is_form_available():
                return request.render('zehntech_form_builder.form_expired_template', {
                    'form': form,
                    'message': form.availability_message or 'This form is currently not available.',
                    'message_on_unpublish': form.availability_message or 'Form not available'
                })

            captcha_fields = form.field_ids.filtered(lambda f: f.field_type == 'captcha')

            if captcha_fields:
                _logger.info('=== CAPTCHA Validation Started ===')
                
                for captcha_field in captcha_fields:
                    field_key = f'field_{captcha_field.id}'
                    captcha_response = post.get(field_key) or request.httprequest.form.get(field_key)
                    
                    _logger.info(f'Captcha field ID: {captcha_field.id}')
                    _logger.info(f'Captcha response received: {bool(captcha_response)}')
                    
                    if not captcha_response:
                        _logger.error('CAPTCHA response not found in form data')
                        return request.render('zehntech_form_builder.form_error_template', {
                            'error_message': 'CAPTCHA verification is required. Please complete the CAPTCHA.'
                        })
                    
                    is_valid = captcha_field.validate_captcha(captcha_response)
                    _logger.info(f'CAPTCHA validation result: {is_valid}')
                    
                    if not is_valid:
                        _logger.error('CAPTCHA validation failed')
                        return request.render('zehntech_form_builder.form_error_template', {
                            'error_message': 'CAPTCHA verification failed. Please try again.'
                        })
                
                _logger.info('=== CAPTCHA Validation Passed ===')

            processed_data = {}
            phone_fields = {}
            address_fields = {} 
            customer_email = None
            email_consent = False
            uploaded_files = {}
            
            form_data = request.httprequest.form
            
            for key in form_data.keys():
                if key in ['csrf_token', 'token']:
                    continue
                    
                if key.startswith('country_code_'):
                    field_id = key.replace('country_code_', '')
                    if field_id not in phone_fields:
                        phone_fields[field_id] = {}
                    phone_fields[field_id]['country_code'] = form_data.get(key)
                elif key.startswith('phone_'):
                    field_id = key.replace('phone_', '')
                    if field_id not in phone_fields:
                        phone_fields[field_id] = {}
                    phone_fields[field_id]['number'] = form_data.get(key)
                elif '_street' in key or '_city' in key or '_state' in key or '_zip' in key or '_country' in key:
                    parts = key.split('_')
                    if len(parts) >= 3:
                        field_id = parts[1]  
                        component = parts[2]  
                        
                        if field_id not in address_fields:
                            address_fields[field_id] = {}
                        address_fields[field_id][component] = form_data.get(key)
                elif key.endswith('[]'):  
                    all_values = form_data.getlist(key)
                    clean_key = key.replace('[]', '')
                    processed_data[clean_key] = ', '.join(all_values) if all_values else ''
                elif key == 'email_consent':
                    email_consent_value = form_data.get(key)
                    email_consent = email_consent_value in ['on', True, 'true', '1']
                    processed_data[key] = email_consent
                    _logger.info(f'Controller: email_consent raw value: {repr(email_consent_value)}, processed: {email_consent}')
                else:
                    processed_data[key] = form_data.get(key)

            for field_id, components in address_fields.items():
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

            for field_id, phone_data in phone_fields.items():
                country_code = phone_data.get('country_code', '')
                phone_number = phone_data.get('number', '')
                
                if country_code and phone_number:
                    combined_phone = f"+{country_code}{phone_number}"
                elif phone_number:
                    combined_phone = phone_number
                else:
                    combined_phone = ""
                    
                processed_data[f'field_{field_id}'] = combined_phone

            _logger.info(f'Request files keys: {list(request.httprequest.files.keys())}')
            _logger.info(f'All form keys: {list(form_data.keys())}')
            for key in request.httprequest.files:
                _logger.info(f'Processing file key: {key}')
                if key.startswith('field_'):
                    files = request.httprequest.files.getlist(key)
                    _logger.info(f'Files found for {key}: {len(files)} file(s)')
                    if files:
                        file_data = []
                        for file in files:
                            if file and file.filename:
                                try:
                                    file_content = base64.b64encode(file.read())
                                    file_data.append({
                                        'filename': file.filename,
                                        'content': file_content.decode('utf-8'),
                                        'mimetype': file.content_type or 'application/octet-stream'
                                    })
                                except Exception as e:
                                    _logger.error(f'Error processing file {file.filename}: {str(e)}')
                                    _logger.error(f'File details - Size: {file.content_length}, Type: {file.content_type}')
                                    import traceback
                                    _logger.error(traceback.format_exc())
                        
                        if file_data:
                            uploaded_files[key] = file_data if len(file_data) > 1 else file_data[0]
                        else:
                            uploaded_files[key] = None

            processed_data.update(uploaded_files)

            for key, value in processed_data.items():
                if key.startswith('field_'):
                    field_id = key.replace('field_', '')
                    field = form.field_ids.filtered(lambda f: str(f.id) == field_id and f.field_type == 'email')
                    if field and value:
                        customer_email = value
                        break

            if not form.check_response_limit(customer_email):
                return request.render('zehntech_form_builder.form_error_template', {
                    'error_message': 'You have already submitted a response to this form.'
                })

            filtered_data = {}
            for key, value in processed_data.items():
                if key.startswith('field_'):
                    field_id = key.replace('field_', '').split('_')[0]  
                    field = form.field_ids.filtered(lambda f: str(f.id) == field_id)
                    if field and field.field_type != 'captcha':
                        filtered_data[key] = value
                elif key not in ['csrf_token', 'token']:  
                    filtered_data[key] = value

            submission = request.env['form.submission'].sudo().create({
                'form_id': form.id,
                'submitted_data': json.dumps(filtered_data),
                'customer_email': customer_email,
            })

            if form.email_notifications_enabled:
                try:
                    import threading
                    thread = threading.Thread(target=form._send_emails_async, args=(processed_data,))
                    thread.start()
                except Exception as email_error:
                    _logger.error(f'Failed to start email thread: {str(email_error)}')
            
            return request.redirect(f'/form_builder/thank_you/{token}?lang={lang_param}')

        except Exception as e:
            _logger.error(f'Error during form submission: {str(e)}')
            return request.render('zehntech_form_builder.form_error_template', {
                'error_message': 'An error occurred while processing your submission. Please try again.'
            })

    @http.route(['/form_builder/thank_you/<string:token>'], type='http', auth="public", website=True, csrf=False)
    def thank_you_page(self, token, **kwargs):
        form = request.env['form.builder'].sudo().search([('share_token', '=', token)], limit=1)
        
        if not form:
            return request.not_found()
        
        lang_param = kwargs.get('lang') or request.httprequest.args.get('lang') or 'en'
        form_url_with_lang = f'/form_builder/shared/{token}?lang={lang_param}'
        
        return request.render('zehntech_form_builder.form_thank_you_template', {
            'thank_you_message': form.thank_you_message or "Thank you for submitting the form!",
            'form_url': form_url_with_lang,
            'user_lang': lang_param,
        })
            

    @http.route('/form_builder/responses/<int:form_id>', type='http', auth='user', website=True)
    def form_responses_view(self, form_id, page=1, order='desc', **kwargs):
        form = request.env['form.builder'].sudo().browse(form_id)
        if not form.exists():
            return request.not_found()

        page = int(page) if page else 1
        per_page = 10
        offset = (page - 1) * per_page
        
        order_by = 'submitted_on desc' if order == 'desc' else 'submitted_on asc'
        
        total_submissions = request.env['form.submission'].sudo().search_count([('form_id', '=', form.id)])
        total_pages = (total_submissions + per_page - 1) // per_page
        
        submissions = request.env['form.submission'].sudo().search(
            [('form_id', '=', form.id)], 
            order=order_by, 
            limit=per_page, 
            offset=offset
        )
        
        field_defs = form.field_ids.filtered(lambda f: f.field_type not in ['button', 'captcha'])

        show_actual_password = True
        processed_submissions = []
        for submission in submissions:
            if isinstance(submission.submitted_data, str):
                try:
                    import json
                    submission.submitted_data = json.loads(submission.submitted_data)
                except (json.JSONDecodeError, TypeError):
                    submission.submitted_data = {}
            elif not isinstance(submission.submitted_data, dict):
                submission.submitted_data = {}
            processed_submissions.append(submission)

        pagination = {
            'current_page': page,
            'total_pages': total_pages,
            'has_previous': page > 1,
            'has_next': page < total_pages,
            'previous_page': page - 1 if page > 1 else None,
            'next_page': page + 1 if page < total_pages else None,
            'start_record': offset + 1,
            'end_record': min(offset + per_page, total_submissions),
            'total_records': total_submissions
        }

        return request.render('zehntech_form_builder.form_response_table_template', {
            'form': form,
            'submissions': processed_submissions,
            'fields': field_defs,
            'pagination': pagination,
            'current_order': order,
            'show_actual_password': True,
        })

    @http.route('/form_builder/export/<int:form_id>', type='http', auth='user')
    def export_form_responses(self, form_id, **kwargs):
        """Export form responses to CSV"""
        form = request.env['form.builder'].sudo().browse(form_id)
        if not form.exists():
            return request.not_found()

        submissions = request.env['form.submission'].sudo().search([('form_id', '=', form.id)], order='submitted_on desc')
        field_defs = form.field_ids.filtered(lambda f: f.field_type not in ['button', 'captcha'])

        output = StringIO()
        writer = csv.writer(output)
        
        headers = [_('Submission ID'), _('Submitted On')]
        for field in field_defs:
            headers.append(field.label)
        writer.writerow(headers)
        
        for submission in submissions:
            if isinstance(submission.submitted_data, str):
                try:
                    import json
                    submitted_data = json.loads(submission.submitted_data)
                except (json.JSONDecodeError, TypeError):
                    submitted_data = {}
            else:
                submitted_data = submission.submitted_data or {}
                
            row = [
                submission.id,
                submission.submitted_on.strftime('%Y-%m-%d') if submission.submitted_on else ''
            ]
            
            for field in field_defs:
                field_key = f'field_{field.id}'
                value = submitted_data.get(field_key, '')
                
                if field.field_type == 'address' and f'{field_key}_components' in submitted_data:
                    components = submitted_data[f'{field_key}_components']
                    address_parts = []
                    for part in ['street', 'city', 'state', 'zip', 'country']:
                        if components.get(part):
                            address_parts.append(f"{part.title()}: {components[part]}")
                    value = ' | '.join(address_parts) if address_parts else value

                elif field.field_type == 'file':
                    if isinstance(value, list):
                        filenames = [f.get('filename', 'Unknown') for f in value if isinstance(f, dict)]
                        value = ', '.join(filenames) if filenames else 'No files'
                    elif isinstance(value, dict):
                        value = value.get('filename', 'No file')
                    else:
                        value = 'No file'
                
                row.append(str(value))
            
            writer.writerow(row)
        
        csv_data = output.getvalue()
        output.close()
        
        filename = f"{form.name.replace(' ', '_')}_responses.csv"
        
        response = Response(
            csv_data,
            mimetype='text/csv',
            headers={
                'Content-Disposition': f'attachment; filename="{filename}"'
            }
        )
        
        return response

    @http.route('/form_builder/view_file/<int:submission_id>/<string:field_id>/<int:file_index>', type='http', auth='user')
    def view_file(self, submission_id, field_id, file_index, **kwargs):
        """View uploaded file"""
        submission = request.env['form.submission'].sudo().browse(submission_id)
        if not submission.exists():
            return request.not_found()
        
        submitted_data = submission.submitted_data
        if isinstance(submitted_data, str):
            submitted_data = json.loads(submitted_data)
        
        field_key = f'field_{field_id}'
        file_data = submitted_data.get(field_key)
        
        if not file_data:
            return request.not_found()
        
        if isinstance(file_data, list):
            if file_index >= len(file_data):
                return request.not_found()
            file_info = file_data[file_index]
        else:
            file_info = file_data
        
        file_content = base64.b64decode(file_info['content'])
        
        return request.make_response(
            file_content,
            headers=[
                ('Content-Type', file_info.get('mimetype', 'application/octet-stream')),
                ('Content-Disposition', f'inline; filename="{file_info["filename"]}"')
            ]
        )

    @http.route('/form_builder/download_file/<int:submission_id>/<string:field_id>/<int:file_index>', 
                type='http', auth='user')
    def download_file(self, submission_id, field_id, file_index, **kwargs):
        """Download uploaded file"""
        submission = request.env['form.submission'].sudo().browse(submission_id)
        if not submission.exists():
            return request.not_found()
        
        submitted_data = submission.submitted_data
        if isinstance(submitted_data, str):
            submitted_data = json.loads(submitted_data)
        
        field_key = f'field_{field_id}'
        file_data = submitted_data.get(field_key)
        
        if not file_data:
            return request.not_found()
        
        if isinstance(file_data, list):
            if file_index >= len(file_data):
                return request.not_found()
            file_info = file_data[file_index]
        else:
            file_info = file_data
        
        file_content = base64.b64decode(file_info['content'])
        
        return request.make_response(
            file_content,
            headers=[
                ('Content-Type', file_info.get('mimetype', 'application/octet-stream')),
                ('Content-Disposition', f'attachment; filename="{file_info["filename"]}"')
            ]
        )


    