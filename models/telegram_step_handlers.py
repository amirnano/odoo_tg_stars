from odoo import models
import logging
import json

_logger = logging.getLogger(__name__)

class TelegramStepHandlers(models.AbstractModel):
    _name = 'telegram.step.handlers'
    _description = 'پردازش‌کننده‌های مراحل تلگرام'

    def handle_contact_request(self, participant, step, message=None, is_restart=False):
        """پردازش درخواست شماره تماس"""
        if is_restart and participant.is_step_completed(step):
            _logger.info(f"Skipping contact request step {step.name} in restart mode as it's already completed.")
            return {'success': True}

        _logger.info(f"Processing contact request step with message: {message}")
        
        if not message:
            # نمایش دکمه اشتراک‌گذاری شماره تماس
            service = self.env['telegram.service'].sudo().with_context(bot_id=participant.bot_id.id).new()
            reply_markup = {
                'keyboard': [[{
                    'text': 'اشتراک‌گذاری شماره تماس',
                    'request_contact': True
                }]],
                'resize_keyboard': True,
                'one_time_keyboard': True
            }
            
            result = service.send_message(
                chat_id=participant.chat_id,
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
                
            if not user_id or str(user_id) != str(participant.telegram_id):
                _logger.error(f"User ID mismatch: {user_id} != {participant.telegram_id}")
                return {'error': 'لطفاً شماره تماس خود را به اشتراک بگذارید'}
                
            # ذخیره شماره تماس و فعال‌سازی کاربر
            if not phone.startswith('+'):
                phone = '+' + phone
                
            _logger.info(f"Saving phone number {phone} to partner {participant.partner_id}")
            participant.partner_id.write({
                'phone': phone,
                'active': True  # فعال‌سازی کاربر پس از دریافت شماره تماس
            })
            
            # حذف کیبورد
            service = self.env['telegram.service'].sudo().with_context(bot_id=participant.bot_id.id).new()
            service.remove_keyboard(participant.chat_id)
            
            # انتقال به مرحله بعد
            next_step = participant._get_next_step(step)
            if next_step:
                _logger.info(f"Moving to next step: {next_step.name}")
                participant.write({'current_step_id': next_step.id})
                # The controller will handle the next step
            return {'success': True}
        
        return {'error': 'داده نامعتبر'}

    def handle_save_info(self, participant, step, message=None, is_restart=False):
        """پردازش ذخیره اطلاعات"""
        if is_restart and participant.is_step_completed(step):
            _logger.info(f"Skipping save info step {step.name} in restart mode as it's already completed.")
            return {'success': True}
            
        if not message:
            service = self.env['telegram.service'].sudo().with_context(bot_id=participant.bot_id.id).new()
            service.send_message(
                chat_id=participant.chat_id,
                message=step.content
            )
            return {'success': True, 'waiting_input': True}
        else:
            try:
                is_valid, validation_result = step.validate_input(message)
                if not is_valid:
                    service = self.env['telegram.service'].sudo().with_context(bot_id=participant.bot_id.id).new()
                    service.send_message(
                        chat_id=participant.chat_id,
                        message=validation_result if isinstance(validation_result, str) else 'خطای نامشخص'
                    )
                    return {'success': False, 'error': validation_result}
                
                if step.target_model_id and step.target_field_id:
                    model = self.env[step.target_model_id.model]
                    record = model.browse(participant.partner_id.id)
                    
                    value = message
                    if step.target_field_id.ttype == 'many2one' and isinstance(validation_result, dict) and 'id' in validation_result:
                        value = validation_result['id']
                        
                    record.write({step.target_field_id.name: value})
                    
                    field_key = f"{step.target_model_id.model}.{step.target_field_id.name}"
                    participant._add_completed_field(field_key)
                    
                    next_step = participant._get_next_step(step)
                    if next_step:
                        participant.write({'current_step_id': next_step.id})
                        # The controller will handle the next step
                    return {'success': True}
                    
                return {'error': 'مدل یا فیلد تعریف نشده است'}
            except Exception as e:
                _logger.error(f"خطا در ذخیره اطلاعات: {str(e)}")
                return {'error': str(e)}

    def handle_option_select(self, participant, step, message=None, is_restart=False):
        """پردازش انتخاب گزینه"""
        if is_restart and participant.is_step_completed(step):
            _logger.info(f"Skipping option select step {step.name} in restart mode as it's already completed.")
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
            service = self.env['telegram.service'].sudo().with_context(bot_id=participant.bot_id.id).new()
            result = service.send_message(
                chat_id=participant.chat_id,
                message=step.content,
                reply_markup=json.dumps(reply_markup)
            )

            _logger.info(f"Message sent with result: {result}")
            return result

        except Exception as e:
            _logger.error(f"Error in option_select step: {str(e)}")
            return {'error': str(e)}