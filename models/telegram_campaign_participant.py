from odoo import models, fields, api
import logging

class TelegramCampaignParticipant(models.Model):
    _name = 'telegram.campaign.participant'
    _description = 'شرکت‌کنندگان کمپین تلگرام'
    _order = 'join_date desc'

    campaign_id = fields.Many2one('telegram.campaign', string='کمپین', required=True, ondelete='cascade')
    telegram_info_id = fields.Many2one('telegram.info', string='اطلاعات تلگرام', ondelete='cascade')
    
    partner_id = fields.Many2one(related='telegram_info_id.partner_id', string='مخاطب', store=True, readonly=True)
    telegram_id = fields.Char(related='telegram_info_id.telegram_id', string='شناسه تلگرام', store=True, readonly=True)
    telegram_username = fields.Char(related='telegram_info_id.telegram_username', string='نام کاربری تلگرام', store=True, readonly=True)
    chat_id = fields.Char(related='telegram_info_id.chat_id', string='شناسه چت', store=True, readonly=True)
    bot_id = fields.Many2one(related='telegram_info_id.bot_id', string='ربات', store=True, readonly=True)
    
    join_date = fields.Datetime(string='تاریخ پیوستن', default=fields.Datetime.now, readonly=True)
    last_start_date = fields.Datetime(string='آخرین شروع', default=fields.Datetime.now)
    current_step_id = fields.Many2one('telegram.step', string='مرحله فعلی', ondelete='set null')
    completed_fields = fields.Text(string='فیلدهای تکمیل شده', help='لیست فیلدهایی که توسط کاربر پر شده‌اند')
    state = fields.Selection([
        ('pending', 'در انتظار'),
        ('active', 'فعال'),
        ('completed', 'تکمیل شده'),
        ('canceled', 'لغو شده')
    ], string='وضعیت', default='pending', required=True)

    _sql_constraints = [
        ('unique_participant',
         'UNIQUE(campaign_id, telegram_info_id)',
         'این کاربر قبلاً در این کمپین ثبت شده است!')
    ]

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

    def _get_next_step(self, current_step):
        """دریافت مرحله بعدی بر اساس sequence"""
        next_steps = self.campaign_id.step_ids.filtered(
            lambda s: s.sequence > current_step.sequence
        ).sorted(lambda s: s.sequence)
        return next_steps[0] if next_steps else None

    def process_forward_message(self, step):
        """پردازش پیام فورواردی"""
        self.ensure_one()
        _logger = logging.getLogger(__name__)

        try:
            if not step.forward_link:
                return {'success': False, 'error': 'No forward link provided'}

            # تجزیه لینک برای دریافت شناسه چت و پیام
            parts = step.forward_link.split('/')
            if len(parts) < 2:
                return {'success': False, 'error': 'Invalid forward link'}

            # استخراج نام کانال و شناسه پیام
            channel_name = parts[-2].replace('@', '')
            message_id = int(parts[-1])

            _logger.info(f"Forwarding message from channel {channel_name} with ID {message_id}")

            service = self.env['telegram.service'].sudo().with_context(
                bot_id=self.bot_id.id
            ).new()

            try:
                if step.forward_with_source:
                    # ارسال با منبع
                    result = service.forward_message(
                        chat_id=self.chat_id,
                        from_chat_id=f"@{channel_name}",
                        message_id=message_id
                    )
                else:
                    # ارسال بدون منبع
                    result = service.copy_message(
                        chat_id=self.chat_id,
                        from_chat_id=f"@{channel_name}",
                        message_id=message_id
                    )

                _logger.info(f"Forward result: {result}")

                if result and step.delete_after:
                    # ثبت برای حذف خودکار
                    self.env['telegram.message.delete'].create({
                        'chat_id': self.chat_id,
                        'message_id': result['result']['message_id'],
                        'bot_id': self.bot_id.id,
                        'step_id': step.id,
                        'delete_time': fields.Datetime.now() + timedelta(minutes=step.delete_delay)
                    })

                return {'success': True}

            except Exception as e:
                _logger.error(f"خطا در پردازش پیام فورواردی: {str(e)}")
                # اگر فوروارد با خطا مواجه شد، متن پیام را ارسال می‌کنیم
                if step.content:
                    service.send_message(
                        chat_id=self.chat_id,
                        message=step.content
                    )
                return {'success': False, 'error': str(e)}

        except Exception as e:
            _logger.error(f"خطا در پردازش پیام فورواردی: {str(e)}")
            return {'success': False, 'error': str(e)}

    def _add_completed_field(self, field_name):
        """اضافه کردن فیلد به لیست فیلدهای تکمیل شده"""
        self.ensure_one()
        completed = self.completed_fields.split(',') if self.completed_fields else []
        if field_name not in completed:  # اگر فیلد قبلاً اضافه نشده
            completed.append(field_name)
            self.completed_fields = ','.join(completed)

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