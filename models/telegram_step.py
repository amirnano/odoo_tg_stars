from odoo import models, fields, api
from odoo.exceptions import ValidationError
import re
import logging
import tempfile
import base64
import os
import mimetypes
import json
import requests
from datetime import datetime, timedelta

_logger = logging.getLogger(__name__)

class TelegramStep(models.Model):
    _name = 'telegram.step'
    _description = 'مراحل کمپین'
    _order = 'sequence'

    # فیلدهای compute شده برای کنترل نمایش
    show_content = fields.Boolean(compute='_compute_field_visibility', store=False)
    show_attachment = fields.Boolean(compute='_compute_field_visibility', store=False)
    show_target_fields = fields.Boolean(compute='_compute_field_visibility', store=False)
    show_validation = fields.Boolean(compute='_compute_field_visibility', store=False)
    show_condition = fields.Boolean(compute='_compute_field_visibility', store=False)
    show_options = fields.Boolean(compute='_compute_field_visibility', store=False)

    name = fields.Char(string='نام', required=True)
    sequence = fields.Integer(string='ترتیب', default=10)
    campaign_id = fields.Many2one('telegram.campaign', string='کمپین', required=True, ondelete='cascade')
    message_type = fields.Selection([
        ('text', 'متن'),
        ('contact_request', 'درخواست شماره تماس'),
        ('conditional_message', 'پیام شرطی'),
        ('save_info', 'ذخیره اطلاعات'),
        ('option_select', 'انتخاب گزینه'),
        ('forward', 'پیام فورواردی'),
        ('payment', 'پرداختی')
    ], string='نوع پیام', required=True, default='text')
    content = fields.Text(string='محتوا')
    
    # فیلدهای مربوط به پیوست
    attachment = fields.Binary(string='فایل پیوست', attachment=True)
    attachment_name = fields.Char(string='نام فایل')

    # فیلدهای مربوط به پرداخت
    price = fields.Float(string='قیمت')
    currency = fields.Selection([
        ('TON', 'TON'),
        ('XTR', 'Telegram Stars')
    ], string='واحد پول', default='TON')
    attachment_type = fields.Selection([
        ('photo', 'تصویر'),
        ('video', 'ویدئو'),
        ('audio', 'صوت'),
        ('document', 'سند')
    ], string='نوع فایل', compute='_compute_attachment_type', store=True)
    
    target_model_id = fields.Many2one('ir.model', string='مدل هدف')
    target_field_id = fields.Many2one('ir.model.fields', string='فیلد هدف',
                                     domain="[('model_id', '=', target_model_id)]")
    condition = fields.Char(string='شرط')

    # فیلدهای اعتبارسنجی
    validation_type = fields.Selection([
        ('none', 'دون اعتبارسنجی'),
        ('text', 'متن'),
        ('number', 'عدد'),
        ('email', 'ایمیل'),
        ('phone', 'تلفن'),
        ('contact', 'مخاطب تلگرام')
    ], string='نوع اعتبارسنجی', default='none', required=True)
    
    min_length = fields.Integer(string='حداقل طول', default=0)
    max_length = fields.Integer(string='حداکر طول', default=0)
    regex_pattern = fields.Char(string='الگوی Regex')
    error_message = fields.Text(string='پیام خطا')

    # اضافه کردن فیلدهای جدید
    delete_after = fields.Boolean(
        string='حذف خودکار پیام',
        help='حذف خودکار پیام پس از مدت زمان مشخص'
    )
    delete_delay = fields.Integer(
        string='تاخیر حذف (دقیقه)',
        default=60,
        help='مدت زمان به دقیقه که پس از آن پیام حذف می‌شود'
    )

    option_ids = fields.One2many('telegram.step.option', 'step_id', string='گزینه‌ها')

    forward_link = fields.Char(string='لینک پیام کانال', 
                         help='لینک پیام کانال برای فوروارد (مثال: https://t.me/channel/1234)')
    forward_with_source = fields.Boolean(string='ارسال با منبع', 
                                   help='اگر فعال باشد، منبع پیام نمایش داده می‌شود')

    @api.depends('attachment_name')
    def _compute_attachment_type(self):
        """تشخیص نوع فایل از پسوند"""
        for record in self:
            if record.attachment_name:
                extension = record.attachment_name.lower().split('.')[-1]
                if extension in ['jpg', 'jpeg', 'png', 'gif']:
                    record.attachment_type = 'photo'
                elif extension in ['mp4', 'avi', 'mkv', '3gp']:
                    record.attachment_type = 'video'
                elif extension in ['mp3', 'wav', 'ogg']:
                    record.attachment_type = 'audio'
                else:
                    record.attachment_type = 'document'
            else:
                record.attachment_type = False

    @api.onchange('message_type')
    def _onchange_message_type(self):
        """تنظیم خودکار فیلدها بر اساس نوع پیام"""
        if self.message_type == 'contact_request':
            # تنظیم خودکار مدل و فیلد هدف برای شماره تماس
            partner_model = self.env['ir.model'].search([('model', '=', 'res.partner')], limit=1)
            phone_field = self.env['ir.model.fields'].search([
                ('model_id', '=', partner_model.id),
                ('name', '=', 'phone')
            ], limit=1)
            
            self.target_model_id = partner_model.id
            self.target_field_id = phone_field.id
            self.validation_type = 'contact'
        elif self.message_type == 'save_info':
            self.validation_type = 'text'

    def validate_input(self, input_value):
        """اعتبارسنجی ورودی کاربر"""
        _logger = logging.getLogger(__name__)
        
        if not input_value:
            return False, 'مقدار ورودی خالی است'

        # برای درخواست مخاطب تلگرام
        if self.validation_type == 'contact':
            _logger.info(f"Validating contact input: {input_value}")
            
            if not isinstance(input_value, dict):
                _logger.error(f"Input is not a dict: {type(input_value)}")
                return False, 'لطفاً از دکمه اشتراک‌گذاری مخاطب استفاده کنید'
            
            # بررسی وجود شماره تماس و user_id
            phone_number = input_value.get('phone_number')
            user_id = input_value.get('user_id')
            telegram_user_id = self.env.context.get('telegram_user_id')
            
            _logger.info(f"Phone Number: {phone_number}")
            _logger.info(f"User ID from contact: {user_id}")
            _logger.info(f"Telegram User ID from context: {telegram_user_id}")
            
            if not phone_number:
                _logger.error("No phone number provided")
                return False, 'شماره تماس دریافت نشد'
            
            if not user_id:
                _logger.error("No user_id in contact data")
                return False, 'این مخاطب متعلق به کاربر تلگرام نیست'
            
            # تبدیل user_id و telegram_user_id به string برای مقایسه
            user_id_str = str(user_id)
            telegram_user_id_str = str(telegram_user_id) if telegram_user_id else ''
            
            _logger.info(f"Comparing user IDs - Contact: {user_id_str}, Telegram: {telegram_user_id_str}")
            
            if user_id_str != telegram_user_id_str:
                _logger.error(f"User ID mismatch: {user_id_str} != {telegram_user_id_str}")
                return False, 'لطفاً شماره تماس خود را به اشتراک بگذارید'
            
            _logger.info("Contact validation successful")
            return True, ''

        # برای فیلدهای many2one
        if self.target_field_id.ttype == 'many2one':
            if isinstance(input_value, str):
                # جستجوی رکورد مرتبط
                related_model = self.env[self.target_field_id.relation]
                domain = [('name', 'ilike', input_value)]
                records = related_model.search(domain)
                
                if not records:
                    # اگر عنوان موجود نبود و مدل res.partner.title است، یک عنوان جدید ایجاد کنیم
                    if self.target_field_id.relation == 'res.partner.title':
                        try:
                            new_title = related_model.create({
                                'name': input_value,
                                'shortcut': input_value
                            })
                            # رگردندن ID به عنوان بخشی از پاسخ
                            return True, {'id': new_title.id}
                        except Exception as e:
                            _logger.error(f"خطا در ایجاد عنوان جدید: {str(e)}")
                            return False, 'خطا در ایجاد عنوان جدید'
                    else:
                        return False, f'مقدار {input_value} در {self.target_field_id.field_description} یافت نشد'
                
                # برگرداندن ID به عنوان بخشی از پاسخ
                return True, {'id': records[0].id}

        # برای سایر انواع اعتبارسنجی
        if isinstance(input_value, dict):
            input_value = input_value.get('phone_number', '')

        # بررسی طول
        if self.min_length > 0 and len(str(input_value)) < self.min_length:
            return False, f'طول ورودی باید حداقل {self.min_length} کاراکتر باشد'
        if self.max_length > 0 and len(str(input_value)) > self.max_length:
            return False, f'طول ورودی باید حداکثر {self.max_length} کاراکتر باشد'

        # اعتبارسنجی بر اساس نوع
        if self.validation_type == 'text':
            if not isinstance(input_value, str) or not input_value.replace(' ', '').isalpha():
                return False, 'لطفاً فقط حروف وارد کنید'
        
        elif self.validation_type == 'number':
            if not str(input_value).isdigit():
                return False, 'لطفاً فقط عدد وارد کنید'
        
        elif self.validation_type == 'email':
            email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
            if not re.match(email_pattern, str(input_value)):
                return False, 'لطفاً یک ایمیل معتبر وارد کنید'
        
        elif self.validation_type == 'phone':
            phone_pattern = r'^\+?[0-9]{10,15}$'
            if not re.match(phone_pattern, str(input_value)):
                return False, 'لطفاً یک ماره تلفن معتبر وارد کنید'

        # اعتبارسنجی با الگوی regex
        if self.regex_pattern and not re.match(self.regex_pattern, str(input_value)):
            return False, self.error_message or 'مقدار ورودی نامعتبر است'

        return True, ''

    @api.onchange('target_model_id')
    def _onchange_target_model(self):
        """به‌روزرسانی دامنه فیلدها وقتی مدل تغییر می‌کند"""
        self.target_field_id = False
        if self.target_model_id:
            return {
                'domain': {
                    'target_field_id': [
                        ('model_id', '=', self.target_model_id.id),
                        ('ttype', 'in', ['char', 'text', 'many2one', 'selection', 'integer', 'float'])
                    ]
                }
            }
        return {'domain': {'target_field_id': []}}

    def _get_field_value(self, record):
        """دریافت مقدار فیلد از رکورد"""
        if self.target_model_id and self.target_field_id:
            try:
                return record[self.target_field_id.name]
            except Exception as e:
                return False
        return False

    @api.constrains('message_type', 'target_model_id', 'target_field_id')
    def _check_save_info_fields(self):
        for record in self:
            if record.message_type == 'save_info':
                if not record.target_model_id or not record.target_field_id:
                    raise ValidationError('بی پیام‌های ذخیره اطلاعات، مدل و فیلد هدف الزامی است')
                # بررسی وجود مدل و فیلد
                try:
                    model = self.env[record.target_model_id.model]
                    if record.target_field_id.name not in model._fields:
                        raise ValidationError(f'فیلد {record.target_field_id.name} در مدل {record.target_model_id.model} وجود ندارد')
                except KeyError:
                    raise ValidationError(f'مدل {record.target_model_id.model} وجود ندارد') 

    def unlink(self):
        """حذف مرحله و گزینه‌های مرتبط"""
        # حذف گزینه‌ها
        self.mapped('option_ids').unlink()
        # حذف ارجاعات به این مرحله در ایر گزینه‌ها
        self.env['telegram.step.option'].search([('next_step_id', 'in', self.ids)]).write({'next_step_id': False})
        return super().unlink()

    def copy(self, default=None):
        """کپی کردن مرحله با تمام گزینه‌ها و تنظیمات"""
        self.ensure_one()
        if default is None:
            default = {}
            
        # کپی کردن مرحله
        new_step = super().copy(default)
        
        # کپی کردن گزینه‌ها
        for option in self.option_ids:
            option.copy({
                'step_id': new_step.id,
                'text': option.text,
                'value': option.value,
                'next_step_id': option.next_step_id.id if option.next_step_id else False,
            })
            
        return new_step

    def process_step(self, telegram_info, message=None):
        """پردازش مرحله"""
        try:
            # اگر پیام متنی یا فورواردی است، همیشه ارسال شود
            if self.message_type in ['text', 'forward']:
                result = self._process_non_interactive_step(telegram_info)
                if not result.get('success'):
                    return result

            self.ensure_one()
            _logger = logging.getLogger(__name__)
            
            if self.message_type == 'save_info':
                if not message:
                    # ارسال درخواست اطلاعات
                    service = self.env['telegram.service'].sudo().with_context(bot_id=telegram_info.bot_id.id).new()
                    result = service.send_message(
                        chat_id=telegram_info.chat_id,
                        message=self.content or 'لطفاً اطلاعات را وارد کنید'
                    )
                    return result
                else:
                    # اعتبارسنجی و ذخیره اطلاعات
                    is_valid, validation_result = self.validate_input(message)
                    if not is_valid:
                        service = self.env['telegram.service'].sudo().with_context(bot_id=telegram_info.bot_id.id).new()
                        service.send_message(
                            chat_id=telegram_info.chat_id,
                            message=validation_result if isinstance(validation_result, str) else 'خطای نامشخص'
                        )
                        return {'error': validation_result}
                    
                    # ذخیره اطلاعات
                    if self.target_model_id and self.target_field_id:
                        model = self.env[self.target_model_id.model]
                        record = model.browse(telegram_info.partner_id.id)
                        record.write({self.target_field_id.name: message})
                    
                    # انتقال به مرحله بعد
                    next_steps = telegram_info.campaign_id.step_ids.filtered(
                        lambda s: s.sequence > self.sequence
                    ).sorted(lambda s: s.sequence)
                    
                    if next_steps:
                        next_step = next_steps[0]
                        telegram_info.write({'current_step_id': next_step.id})
                        return telegram_info.process_step(next_step)
                    
                    return {'success': True}

            # اگر فایل پیوست داریم
            if self.attachment and self.attachment_name:
                _logger.info(f"شروع ارسال فایل {self.attachment_name}")
                
                # تبدیل فایل به باینری
                file_content = base64.b64decode(self.attachment)
                
                try:
                    if self.attachment_type == 'photo':
                        _logger.info("ارسال به صورت تصویر")
                        files = {'photo': ('photo.jpg', file_content, 'image/jpeg')}
                        url = f'https://api.telegram.org/bot{service._get_bot_token(telegram_info.bot_id.id)}/sendPhoto'
                    
                    elif self.attachment_type == 'video':
                        _logger.info("ارسال به صورت ویدئو")
                        files = {'video': ('video.mp4', file_content, 'video/mp4')}
                        url = f'https://api.telegram.org/bot{service._get_bot_token(telegram_info.bot_id.id)}/sendVideo'
                    
                    elif self.attachment_type == 'audio':
                        _logger.info("ارسال به صورت صوت")
                        files = {'audio': ('audio.mp3', file_content, 'audio/mpeg')}
                        url = f'https://api.telegram.org/bot{service._get_bot_token(telegram_info.bot_id.id)}/sendAudio'
                    
                    else:  # document
                        _logger.info("ارسال به صورت سند")
                        files = {'document': (self.attachment_name, file_content, 'application/octet-stream')}
                        url = f'https://api.telegram.org/bot{service._get_bot_token(telegram_info.bot_id.id)}/sendDocument'

                    data = {
                        'chat_id': telegram_info.chat_id,
                        'caption': self.content,
                        'parse_mode': 'HTML'
                    }

                    if self.attachment_type == 'video':
                        data['supports_streaming'] = True

                    _logger.info(f"Sending request to {url}")
                    _logger.info(f"Data: {data}")
                    
                    response = requests.post(url, data=data, files=files, timeout=10)
                    response_data = response.json()
                    
                    _logger.info(f"Response: {response_data}")
                    
                    if not response_data.get('ok'):
                        error_msg = response_data.get('description', 'خطای ناشناخته')
                        _logger.error(f"خطا از تلگرام: {error_msg}")
                        return False
                    
                    # ثبت برای حذف خودکار
                    if self.delete_after:
                        delete_time = fields.Datetime.now() + timedelta(minutes=self.delete_delay)
                        self.env['telegram.message.delete'].create({
                            'chat_id': telegram_info.chat_id,
                            'message_id': response_data['result']['message_id'],
                            'bot_id': telegram_info.bot_id.id,
                            'step_id': self.id,
                            'delete_time': delete_time
                        })
                
                except Exception as e:
                    _logger.error(f"خطا در ارسال فایل: {str(e)}")
                    return False
                
            # اگر فقط متن داریم
            elif self.content:
                if self.message_type == 'conditional_message':
                    content = self.content.format(partner=telegram_info.partner_id)
                else:
                    content = self.content
                    
                result = service.send_message(
                    chat_id=telegram_info.chat_id,
                    message=content,
                    parse_mode='HTML'
                )
                
                # ثبت برای حذف خودکار
                if self.delete_after and result and isinstance(result, dict):
                    delete_time = fields.Datetime.now() + timedelta(minutes=self.delete_delay)
                    self.env['telegram.message.delete'].create({
                        'chat_id': telegram_info.chat_id,
                        'message_id': result['result']['message_id'],
                        'bot_id': telegram_info.bot_id.id,
                        'step_id': self.id,
                        'delete_time': delete_time
                    })
            
            # انتقال به مرحله بعد
            next_steps = self.campaign_id.step_ids.filtered(
                lambda s: s.sequence > self.sequence
            ).sorted(lambda s: s.sequence)
            
            if next_steps:
                next_step = next_steps[0]
                telegram_info.write({'current_step_id': next_step.id})
                return telegram_info.process_step(next_step)
            
            return True
            
        except Exception as e:
            _logger.error(f"خطا در پردازش مرحله: {str(e)}")
            return False

    @api.depends('message_type')
    def _compute_field_visibility(self):
        """محاسبه نمایش/عدم نمایش فیلدها بر اساس نوع پیام"""
        for record in self:
            # پیش‌فرض: همه فیلدها مخفی
            record.show_content = False
            record.show_attachment = False
            record.show_target_fields = False
            record.show_validation = False
            record.show_condition = False
            record.show_options = False

            if record.message_type == 'text':
                record.show_content = True
                record.show_attachment = True
            elif record.message_type == 'option_select':
                record.show_content = True
                record.show_target_fields = True
                record.show_options = True
            elif record.message_type == 'contact_request':
                record.show_content = True
                record.show_target_fields = True
                record.show_validation = True
            elif record.message_type == 'save_info':
                record.show_content = True
                record.show_target_fields = True
                record.show_validation = True
            elif record.message_type == 'conditional_message':
                record.show_content = True
                record.show_condition = True

    @api.onchange('attachment', 'attachment_name')
    def _onchange_attachment(self):
        """تنظیم خودکار نوع فایل در صور تغییر فایل"""
        if self.attachment and self.attachment_name:
            self._compute_attachment_type()

    def process_forward_message(self, telegram_info):
        """پردازش پیام فورواردی"""
        self.ensure_one()
        _logger = logging.getLogger(__name__)
        
        try:
            if not self.forward_link:
                return False
            
            # تجزیه لینک برای دریافت شناسه چت و پیام
            # برای لینک‌های به فرمت https://t.me/cafeeclip/70220
            parts = self.forward_link.split('/')
            if len(parts) < 2:
                return False
            
            # استخراج نام کانال و شناسه پیام
            channel_name = parts[-2].replace('@', '')  # حذف @ از ابتدای نام کانال
            message_id = int(parts[-1])
            
            _logger.info(f"Forwarding message from channel {channel_name} with ID {message_id}")
            
            service = self.env['telegram.service'].sudo().with_context(
                bot_id=telegram_info.bot_id.id
            ).new()
            
            try:
                if self.forward_with_source:
                    # ارسال با منبع
                    result = service.forward_message(
                        chat_id=telegram_info.chat_id,
                        from_chat_id=f"@{channel_name}",
                        message_id=message_id
                    )
                else:
                    # ارسال بدون منبع
                    result = service.copy_message(
                        chat_id=telegram_info.chat_id,
                        from_chat_id=f"@{channel_name}",
                        message_id=message_id
                    )
                    
                _logger.info(f"Forward result: {result}")
                
                if result and self.delete_after:
                    # ثبت برای حذف خودکار
                    self.env['telegram.message.delete'].create({
                        'chat_id': telegram_info.chat_id,
                        'message_id': result['result']['message_id'],
                        'bot_id': telegram_info.bot_id.id,
                        'step_id': self.id,
                        'delete_time': fields.Datetime.now() + timedelta(minutes=self.delete_delay)
                    })
                    
                return result
                
            except Exception as e:
                _logger.error(f"خطا در پردازش پیام فورواردی: {str(e)}")
                # اگر فوروارد با خطا مواجه شد، متن پیام را ارسال می‌کنیم
                if self.content:
                    return service.send_message(
                        chat_id=telegram_info.chat_id,
                        message=self.content
                    )
                return False
                
        except Exception as e:
            _logger.error(f"خطا در پردازش پیام فورواردی: {str(e)}")
            return False

    def _add_navigation_buttons(self, step):
        """اضافه کردن دکمه‌های پیمایش"""
        # دریافت مراحل قبل و بعد
        prev_step = self._get_prev_step(step)
        next_step = self._get_next_step(step)
        
        buttons = []
        if prev_step:
            buttons.append({
                'text': '⬅️ بازگشت',
                'callback_data': f'nav_{prev_step.id}'
            })
        if next_step:
            buttons.append({
                'text': 'ادامه ➡️',
                'callback_data': f'nav_{next_step.id}'
            })
        
        if buttons:
            keyboard = {
                'inline_keyboard': [buttons]
            }
            service = self.env['telegram.service'].sudo().with_context(bot_id=self.bot_id.id).new()
            service.send_message(
                chat_id=self.chat_id,
                message='برای پیمایش بین مراحل از دکمه‌های زیر استفاده کنید:',
                reply_markup=json.dumps(keyboard)
            )