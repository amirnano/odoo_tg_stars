from odoo import models, fields, api
from odoo.exceptions import ValidationError
import logging
import json
from datetime import datetime, timedelta

class TelegramInfo(models.Model):
    _name = 'telegram.info'
    _description = 'اطلاعات تلگرام'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    partner_id = fields.Many2one('res.partner', string='شریک تجاری', required=True, 
                               ondelete='cascade')
    bot_id = fields.Many2one('telegram.bot', string='ربات', required=True, ondelete='cascade')
    telegram_id = fields.Char(string='شناسه تلگرام', required=True)
    telegram_username = fields.Char(string='نام کاربری تلگرام')
    chat_id = fields.Char(string='شناسه چت', required=True)
    bot_start_date = fields.Datetime(string='تاریخ شروع', default=fields.Datetime.now)
    campaign_id = fields.Many2one('telegram.campaign', string='کمپین', ondelete='set null')
    campaign_join_date = fields.Datetime(string='تاریخ پیوستن به کمپین')
    current_step_id = fields.Many2one('telegram.step', string='مرحله فعلی', ondelete='set null')
    completed_fields = fields.Text(string='فیلدهای تکمیل شده', help='لیست فیلدهایی که توسط کاربر پر شده‌اند')

    name = fields.Char(related='partner_id.name', string='نام', store=True)
    phone = fields.Char(related='partner_id.phone', string='تلفن', store=True)
    mobile = fields.Char(related='partner_id.mobile', string='موبایل', store=True)
    email = fields.Char(related='partner_id.email', string='ایمیل', store=True)

    _sql_constraints = [
        ('unique_partner_bot_campaign_telegram', 
         'UNIQUE(partner_id, bot_id, campaign_id, telegram_id)',
         'این کاربر قبلاً برای این ربات و کمپین با این شناسه تلگرام ثبت شده است!')
    ]

    @api.model_create_multi
    def create(self, vals_list):
        """ایجاد رکورد جدید"""
        return super().create(vals_list)

    def join_campaign(self, campaign):
        """پیوستن به کمپین جدید"""
        # ایجاد رکورد جدید برای کمپین جدید
        new_info = self.create({
            'partner_id': self.partner_id.id,
            'bot_id': self.bot_id.id,
            'telegram_id': self.telegram_id,
            'telegram_username': self.telegram_username,
            'chat_id': self.chat_id,
            'campaign_id': campaign.id,
            'campaign_join_date': fields.Datetime.now(),
        })
        return new_info

    def _get_completed_fields(self):
        """دریافت لیست فیلدهای تکمیل شده"""
        self.ensure_one()
        completed_fields = []
        
        # بررسی همه فیلدهای تکمیل شده از همه کمپین‌ها
        telegram_infos = self.env['telegram.info'].sudo().search([
            ('telegram_id', '=', self.telegram_id),
            ('completed_fields', '!=', False)
        ])
        
        for info in telegram_infos:
            if info.completed_fields:
                completed_fields.extend(info.completed_fields.split(','))
        
        return list(set(completed_fields))  # حذف موارد تکراری

    def _add_completed_field(self, field_name):
        """اضافه کردن فیلد به لیست فیلدهای تکمیل شده"""
        self.ensure_one()
        completed = self._get_completed_fields()
        if field_name not in completed:  # اگر فیلد قبلاً اضافه نشده
            completed.append(field_name)
            self.completed_fields = ','.join(completed)

    def process_start_parameter(self, start_parameter):
        """پردازش پارامتر شروع و شروع کمپین"""
        _logger = logging.getLogger(__name__)
        
        try:
            # جستجوی کمپین فعال
            campaign = self.env['telegram.campaign'].sudo().search([
                ('start_parameter', '=', start_parameter),
                ('bot_id', '=', self.bot_id.id),
                ('state', '=', 'active')
            ], limit=1)
            
            if not campaign:
                return False

            self.write({
                'campaign_id': campaign.id,
                'campaign_join_date': fields.Datetime.now(),
                'completed_fields': False
            })

            # بررسی ثبت‌نام قبلی در همین کمپین
            existing_registration = self.env['telegram.info'].sudo().search([
                ('telegram_id', '=', self.telegram_id),
                ('campaign_id', '=', campaign.id),
                ('completed_fields', '!=', False)  # اگر فیلدی تکمیل شده باشد
            ], limit=1)

            if existing_registration:
                # اگر کاربر قبلاً در کمپین شرکت کرده، از مرحله فعلی ادامه می‌دهیم
                first_step = existing_registration.current_step_id or campaign.step_ids.sorted(lambda s: s.sequence)[:1]
                if first_step:
                    return self.process_step(first_step)
                return True

            # ثبت شرکت‌کننده جدید در کمپین
            participant_vals = {
                'campaign_id': campaign.id,
                'telegram_info_id': self.id,
                'join_date': fields.Datetime.now(),
                'partner_id': self.partner_id.id,
                'telegram_id': self.telegram_id,
                'telegram_username': self.telegram_username,
                'chat_id': self.chat_id,
                'bot_id': self.bot_id.id
            }
            
            # ایجاد رکورد جدید شرکت‌کننده
            participant = self.env['telegram.campaign.participant'].sudo().create(participant_vals)
            
            # به‌روزرسانی اطلاعات تلگرام
            self.write({
                'campaign_id': campaign.id,
                'campaign_join_date': participant.join_date,
                'completed_fields': False  # پاک کردن فیلدهای تکمیل شده برای کمپین جدید
            })
            
            _logger.info(f'کاربر {self.chat_id} به کمپین {campaign.name} پیوست')

            # شروع از اولین مرحله
            first_step = campaign.step_ids.sorted(lambda s: s.sequence)[:1]
            if first_step:
                self.write({'current_step_id': first_step.id})
                # اجرای مرحله اول
                return self.process_step(first_step)

            return True
            
        except Exception as e:
            _logger.error(f'خطا در پردازش پارامتر شروع {start_parameter}: {str(e)}')
            return False

    def _should_skip_step(self, step):
        """بررسی اینکه آیا مرحله باید رد شود"""
        _logger = logging.getLogger(__name__)
        
        # پیام‌های متنی و فورواردی همیشه باید ارسال شوند
        if step.message_type in ['text', 'forward', 'conditional_message']:
            return False
        
        # برای سایر انواع پیام، بررسی تکمیل قبلی
        if step.target_model_id and step.target_field_id:
            field_key = f"{step.target_model_id.model}.{step.target_field_id.name}"
            completed_fields = self._get_completed_fields()
            
            if field_key in completed_fields:
                _logger.info(f"Step {step.name} already completed (field: {field_key})")
                return True
            
        return False

    def process_step(self, step, message=None, is_restart=False):
        """پردازش مرحله کمپین"""
        self.ensure_one()
        _logger = logging.getLogger(__name__)
        handlers = self.env['telegram.step.handlers']
        
        try:
            # بررسی آخرین پیام شرطی
            last_conditional = self.campaign_id.step_ids.filtered(
                lambda s: s.message_type == 'conditional_message'
            ).sorted(lambda s: s.sequence, reverse=True)[:1]
            
            # در استارت مجدد، اگر آخرین پیام شرطی است فقط آن را نمایش بده
            if is_restart and last_conditional:
                if step.id != last_conditional.id:
                    return {'success': True}

            # پردازش پیام بر اساس نوع
            if step.message_type == 'payment':
                service = self.env['telegram.service'].sudo().with_context(bot_id=self.bot_id.id, step_id=step.id).new()
                service.send_message(chat_id=self.chat_id, message='')
                return {'success': True, 'payment_sent': True}
            
            if step.message_type in ['text', 'forward']:
                service = self.env['telegram.service'].sudo().with_context(bot_id=self.bot_id.id).new()
                if step.attachment:
                    result = service.send_file(
                        chat_id=self.chat_id,
                        step=step,
                        caption=step.content
                    )
                else:
                    result = service.send_message(
                        chat_id=self.chat_id,
                        message=step.content,
                        parse_mode='HTML'
                    )
                if not result:
                    return {'error': 'خطا در ارسال پیام'}

                # اضافه کردن این قسمت برای رفتن به مرحله بعد
                next_step = self._get_next_step(step)
                if next_step:
                    self.write({'current_step_id': next_step.id})
                    return self.process_step(next_step)

            elif step.message_type == 'forward':
                result = step.process_forward_message(self)
                if not result.get('success'):
                    return result

            elif step.message_type == 'contact_request':
                return handlers.handle_contact_request(self, step, message, is_restart)
            
            elif step.message_type == 'save_info':
                return handlers.handle_save_info(self, step, message, is_restart)
            
            elif step.message_type == 'option_select':
                return handlers.handle_option_select(self, step, message, is_restart)
            
            elif step.message_type == 'conditional_message':
                content = step.content.format(partner=self.partner_id)
                service = self.env['telegram.service'].sudo().with_context(bot_id=self.bot_id.id).new()
                result = service.send_message(
                    chat_id=self.chat_id,
                    message=content,
                    parse_mode='HTML'
                )
                if not result:
                    return {'error': 'خطا در ارسال پیام'}

            # به روز رسانی مرحله فعلی
            self.write({'current_step_id': step.id})

            # رفتن به مرحله بعد برای پیام‌های متنی و فورواردی
            if step.message_type in ['text', 'forward']:
                next_step = self._get_next_step(step)
                if next_step:
                    return self.process_step(next_step)

            return {'success': True}

        except Exception as e:
            _logger.error(f"Error processing step: {str(e)}")
            return {'error': str(e)}

    def _process_non_interactive_step(self, step):
        """پردازش مراحل غیر تعاملی (متن و فوروارد)"""
        if step.message_type == 'forward':
            return step.process_forward_message(self)
        else:  # text
            service = self.env['telegram.service'].sudo().with_context(bot_id=self.bot_id.id).new()
            if step.attachment:
                result = service.send_file(
                    chat_id=self.chat_id,
                    step=step,
                    caption=step.content
                )
            else:
                result = service.send_message(
                    chat_id=self.chat_id,
                    message=step.content,
                    parse_mode='HTML'
                )
            return {'success': True} if result else {'error': 'خطا در ارسال پیام'}

    def _get_next_step(self, current_step):
        """دریافت مرحله بعدی بر اساس sequence"""
        next_steps = self.campaign_id.step_ids.filtered(
            lambda s: s.sequence > current_step.sequence
        ).sorted(lambda s: s.sequence)
        return next_steps[0] if next_steps else None

    def process_option_selection(self, callback_data, message=None):
        """پردازش انتخاب گزینه"""
        self.ensure_one()
        _logger = logging.getLogger(__name__)
        
        try:
            # پیدا کردن گزینه انتخاب شده
            option = self.env['telegram.step.option'].sudo().browse(int(callback_data))
            if not option:
                return {'error': 'گزینه یافت نشد'}
            
            _logger.info(f"Selected option: {option.text} with value: {option.value}")
            
            # ذخیره مقدار
            if option.step_id.target_model_id and option.step_id.target_field_id:
                model_name = option.step_id.target_model_id.model
                field_name = option.step_id.target_field_id.name
                
                # اصلاح ذخیره مقدار
                if model_name == 'res.partner':
                    if field_name == 'title':
                        # برای فیلد title باید رکورد title را پیدا یا ایجاد کنیم
                        title = self.env['res.partner.title'].sudo().search([
                            ('name', '=', option.value)
                        ], limit=1)
                        if not title:
                            title = self.env['res.partner.title'].sudo().create({
                                'name': option.value,
                                'shortcut': option.value
                            })
                        value = title.id
                    else:
                        value = option.value
                    
                    self.partner_id.write({field_name: value})
                    
                    # اضافه کردن به فیلدهای تکمیل شده
                    field_key = f"{model_name}.{field_name}"
                    self._add_completed_field(field_key)
                    
                # حذف پیام سوال
                if message:
                    service = self.env['telegram.service'].sudo().with_context(bot_id=self.bot_id.id).new()
                    service.delete_message(self.chat_id, message['message_id'])
                
                # رفتن به مرحله بعد
                next_step = self._get_next_step(option.step_id)
                if next_step:
                    self.write({'current_step_id': next_step.id})
                    return self.process_step(next_step)
                    
            return {'success': True}
            
        except Exception as e:
            _logger.error(f"Error in process_option_selection: {str(e)}")
            return {'error': str(e)}

    def unlink(self):
        """حذف رکورد و رکوردهای وابسته"""
        return super().unlink()

    def process_message(self, message):
        """پردازش پیام دریافتی"""
        self.ensure_one()
        _logger = logging.getLogger(__name__)
        
        try:
            step = self.current_step_id
            if not step:
                return ''
            
            if step.target_model_id and step.target_field_id:
                # ذخیره مقدار در فیلد هدف
                model_name = step.target_model_id.model
                field_name = step.target_field_id.name
                record = getattr(self, step.target_model_field_id.name)
                
                if not record:
                    return ''
                
                # پردازش و ذخیره مقدار
                value = message
                if field_name == 'title':
                    title = self.env['res.partner.title'].sudo().search([
                        ('name', '=', message)
                    ], limit=1)
                    if title:
                        value = title.id
                        
                elif field_name == 'category_id':
                    category = self.env['res.partner.category'].sudo().search([
                        ('name', '=', message)
                    ], limit=1)
                    if not category:
                        category = self.env['res.partner.category'].sudo().create({
                            'name': message
                        })
                    value = category.id
                    
                # ذخیره مقدار
                record.write({field_name: value})
                
                # اضافه کردن به فیلدهای تکمیل شده
                field_key = f"{model_name}.{field_name}"
                self._add_completed_field(field_key)
                
                # بررسی آیا این آخرین مرحله ذخیره اطلاعات است
                remaining_info_steps = self.campaign_id.step_ids.filtered(
                    lambda s: s.sequence > step.sequence and s.target_model_id
                )
                
                if not remaining_info_steps:
                    # ارسال همه پیام‌های باقیمانده به ترتیب
                    remaining_messages = self.campaign_id.step_ids.filtered(
                        lambda s: s.sequence > step.sequence and s.message_type in ['text', 'forward', 'conditional_message']
                    ).sorted(lambda s: s.sequence)
                    
                    _logger.info(f"Sending remaining messages: {len(remaining_messages)} messages")
                    
                    for msg_step in remaining_messages:
                        _logger.info(f"Processing message step: {msg_step.name}")
                        self.write({'current_step_id': msg_step.id})
                        self.process_step(msg_step)
                    
                    return ''
                else:
                    # حرکت به مرحله بعدی ذخیره اطلاعات
                    next_step = remaining_info_steps[0]
                    self.write({'current_step_id': next_step.id})
                    return self.process_step(next_step)
                    
            return ''
            
        except Exception as e:
            _logger.error('خطا در ذخیره اطلاعات: %s', str(e))
            return ''

    def process_navigation(self, step_id):
        """پردازش دکمه‌های پیمایش"""
        step = self.env['telegram.step'].browse(int(step_id))
        if not step:
            return {'error': 'مرحله یافت نشد'}
        
        self.write({'current_step_id': step.id})
        return self.process_step(step)
