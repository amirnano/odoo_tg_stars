from odoo import models
import logging
import json

_logger = logging.getLogger(__name__)

class TelegramStepHandlers(models.AbstractModel):
    _name = 'telegram.step.handlers'
    _description = 'پردازش‌کننده‌های مراحل تلگرام'

    def handle_contact_request(self, telegram_info, step, message=None, is_restart=False):
        """پردازش درخواست شماره تماس"""
        if is_restart:
            _logger.info(f"Skipping contact request step {step.name} in restart mode")
            return {'success': True}

        _logger.info(f"Processing contact request step with message: {message}")
        
        # بررسی اینکه آیا شماره تماس قبلاً ذخیره شده است
        if telegram_info.partner_id.phone:
            _logger.info(f"Phone number already exists: {telegram_info.partner_id.phone}")
            # نمایش دکمه مشاهده پروفایل
            service = self.env['telegram.service'].sudo().with_context(bot_id=telegram_info.bot_id.id).new()
            keyboard = {
                'keyboard': [[{
                    'text': 'مشاهده پروفایل',
                    'web_app': {'url': f'/web#id={telegram_info.partner_id.id}&model=res.partner&view_type=form'}
                }]],
                'resize_keyboard': True,
                'one_time_keyboard': True
            }
            service.send_message(
                chat_id=telegram_info.chat_id,
                message=f"شماره تماس شما: {telegram_info.partner_id.phone}",
                reply_markup=json.dumps(keyboard)
            )
            # انتقال به مرحله بعد
            next_steps = telegram_info.campaign_id.step_ids.filtered(
                lambda s: s.sequence > step.sequence
            ).sorted(lambda s: s.sequence)
            if next_steps:
                next_step = next_steps[0]
                telegram_info.write({'current_step_id': next_step.id})
                return telegram_info.process_step(next_step)
            return {'success': True}
            
        if not message:
            # نمایش دکمه اشتراک‌گذاری شماره تماس
            service = self.env['telegram.service'].sudo().with_context(bot_id=telegram_info.bot_id.id).new()
            reply_markup = {
                'keyboard': [[{
                    'text': 'اشتراک‌گذاری شماره تماس',
                    'request_contact': True
                }]],
                'resize_keyboard': True,
                'one_time_keyboard': True
            }
            
            result = service.send_message(
                chat_id=telegram_info.chat_id,
                message=step.content or 'لطفاً شماره تماس خود را به اشتراک بگذارید',
                reply_markup=json.dumps(reply_markup)
            )
            return result
            
        elif isinstance(message, dict) and ('phone_number' in message or 'contact' in message):
            # پردازش شماره تماس دریافتی
            contact = message if 'phone_number' in message else message.get('contact', {})
            _logger.info(f"Received contact data: {contact}")
            
            phone = contact.get('phone_number')
            user_id = contact.get('user_id')
            
            if not phone:
                _logger.error("No phone number in contact data")
                return {'error': 'شماره تماس دریافت نشد'}
                
            if not user_id or str(user_id) != str(telegram_info.telegram_id):
                _logger.error(f"User ID mismatch: {user_id} != {telegram_info.telegram_id}")
                return {'error': 'لطفاً شماره تماس خود را به اشتراک بگذارید'}
                
            # ذخیره شماره تماس و فعال‌سازی کاربر
            if not phone.startswith('+'):
                phone = '+' + phone
                
            _logger.info(f"Saving phone number {phone} to partner {telegram_info.partner_id}")
            telegram_info.partner_id.write({
                'phone': phone,
                'active': True  # فعال‌سازی کاربر پس از دریافت شماره تماس
            })
            
            # حذف کیبورد
            service = self.env['telegram.service'].sudo().with_context(bot_id=telegram_info.bot_id.id).new()
            service.remove_keyboard(telegram_info.chat_id)
            
            # انتقال به مرحله بعد
            next_steps = telegram_info.campaign_id.step_ids.filtered(
                lambda s: s.sequence > step.sequence
            ).sorted(lambda s: s.sequence)
            
            if next_steps:
                next_step = next_steps[0]
                _logger.info(f"Moving to next step: {next_step.name}")
                telegram_info.write({'current_step_id': next_step.id})
                return telegram_info.process_step(next_step)
                
            return {'success': True}
        
        return {'error': 'داده نامعتبر'}

    def handle_save_info(self, telegram_info, step, message=None, is_restart=False):
        """پردازش ذخیره اطلاعات"""
        if is_restart:
            _logger.info(f"Skipping save info step {step.name} in restart mode")
            return {'success': True}
            
        if not message:
            service = self.env['telegram.service'].sudo().with_context(bot_id=telegram_info.bot_id.id).new()
            service.send_message(
                chat_id=telegram_info.chat_id,
                message=step.content
            )
            return {'success': True, 'waiting_input': True}
        else:
            try:
                is_valid, validation_result = step.validate_input(message)
                if not is_valid:
                    service = self.env['telegram.service'].sudo().with_context(bot_id=telegram_info.bot_id.id).new()
                    service.send_message(
                        chat_id=telegram_info.chat_id,
                        message=validation_result if isinstance(validation_result, str) else 'خطای نامشخص'
                    )
                    return {'success': False, 'error': validation_result}
                
                if step.target_model_id and step.target_field_id:
                    model = self.env[step.target_model_id.model]
                    record = model.browse(telegram_info.partner_id.id)
                    
                    # برای فیلدهای many2one
                    if step.target_field_id.ttype == 'many2one':
                        if isinstance(validation_result, dict) and 'id' in validation_result:
                            value = validation_result['id']
                        else:
                            value = False
                    else:
                        value = message
                        
                    record.write({step.target_field_id.name: value})
                    
                    # اضافه کردن فیلد به لیست فیلدهای تکمیل شده
                    field_key = f"{step.target_model_id.model}.{step.target_field_id.name}"
                    telegram_info._add_completed_field(field_key)
                    
                    # انتقال به مرحله بعد
                    next_steps = telegram_info.campaign_id.step_ids.filtered(
                        lambda s: s.sequence > step.sequence
                    ).sorted(lambda s: s.sequence)
                    
                    if next_steps:
                        next_step = next_steps[0]
                        telegram_info.write({'current_step_id': next_step.id})
                        return telegram_info.process_step(next_step)
                    return {'success': True}
                    
                return {'error': 'مدل یا فیلد تعریف نشده است'}
            except Exception as e:
                _logger.error(f"خطا در ذخیره اطلاعات: {str(e)}")
                return {'error': str(e)}

    def handle_option_select(self, telegram_info, step, message=None, is_restart=False):
        """پردازش انتخاب گزینه"""
        if is_restart:
            _logger.info(f"Skipping option select step {step.name} in restart mode")
            return {'success': True}
            
        _logger.info(f"Processing option_select step: {step.name}")
        try:
            # بررسی وجود گزینه‌ها
            if not step.option_ids:
                _logger.error("No options defined for option_select step")
                return {'error': 'گزینه‌ای تعریف نشده است'}

            # ساخت دکمه‌های inline
            buttons = []
            for option in step.option_ids:
                _logger.info(f"Adding button: text={option.text}, callback_data={option.id}")
                buttons.append({
                    'text': option.text,
                    'callback_data': str(option.id)
                })

            # ساختار InlineKeyboardMarkup
            keyboard = [[button] for button in buttons]  # هر دکمه در یک ردیف
            reply_markup = {
                'inline_keyboard': keyboard
            }

            _logger.info(f"Sending message with keyboard: {json.dumps(reply_markup)}")

            # ارسال پیام با دکمه‌ها
            service = self.env['telegram.service'].sudo().with_context(bot_id=telegram_info.bot_id.id).new()
            result = service.send_message(
                chat_id=telegram_info.chat_id,
                message=step.content,
                reply_markup=json.dumps(reply_markup)
            )

            _logger.info(f"Message sent with result: {result}")
            return result

        except Exception as e:
            _logger.error(f"Error in option_select step: {str(e)}")
            return {'error': str(e)} 