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

    name = fields.Char(string='نام', required=True)
    sequence = fields.Integer(string='ترتیب', default=10)
    campaign_id = fields.Many2one('telegram.campaign', string='کمپین', required=True, ondelete='restrict')
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

    @api.returns('self', lambda value: value.id)
    def copy(self, default=None):
        """کپی کردن مرحله با تمام گزینه‌ها و تنظیمات"""
        self.ensure_one()
        if default is None:
            default = {}
        if 'name' not in default:
            default['name'] = f"{self.name} (کپی)"
        return super().copy(default)



    @api.onchange('attachment', 'attachment_name')
    def _onchange_attachment(self):
        """تنظیم خودکار نوع فایل در صور تغییر فایل"""
        if self.attachment and self.attachment_name:
            self._compute_attachment_type()


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