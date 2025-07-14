from odoo import models
import logging
import json

_logger = logging.getLogger(__name__)

class TelegramStepHandlers(models.AbstractModel):
    _name = 'telegram.step.handlers'
    _description = 'پردازش‌کننده‌های مراحل تلگرام'

    def handle_contact_request(self, participant, step, message=None, is_restart=False):
        if is_restart and participant.is_step_completed(step):
            return {'success': True}

        if not message:
            service = self.env['telegram.service'].sudo().with_context(bot_id=participant.bot_id.id).new()
            reply_markup = {
                'keyboard': [[{'text': 'اشتراک‌گذاری شماره تماس', 'request_contact': True}]],
                'resize_keyboard': True,
                'one_time_keyboard': True
            }
            service.send_message(
                chat_id=participant.chat_id,
                text=step.content or 'لطفاً شماره تماس خود را به اشتراک بگذارید',
                reply_markup=reply_markup
            )
            return {'success': True, 'waiting_input': True}
        
        contact = message.get('contact', {})
        phone = contact.get('phone_number')
        user_id = contact.get('user_id')

        if not phone or str(user_id) != str(participant.telegram_id):
            service = self.env['telegram.service'].sudo().with_context(bot_id=participant.bot_id.id).new()
            service.send_message(chat_id=participant.chat_id, text='لطفاً شماره تماس خود را به اشتراک بگذارید')
            return {'success': False, 'error': 'Invalid contact'}

        participant.partner_id.write({'phone': phone, 'active': True})
        participant._add_completed_field(f"{step.target_model_id.model}.{step.target_field_id.name}")

        service = self.env['telegram.service'].sudo().with_context(bot_id=participant.bot_id.id).new()
        service.remove_keyboard(participant.chat_id)

        return {'success': True}

    def handle_save_info(self, participant, step, message=None, is_restart=False):
        if is_restart and participant.is_step_completed(step):
            return {'success': True}

        if not message:
            service = self.env['telegram.service'].sudo().with_context(bot_id=participant.bot_id.id).new()
            service.send_message(chat_id=participant.chat_id, text=step.content)
            return {'success': True, 'waiting_input': True}

        text = message.get('text')
        is_valid, validation_result = step.validate_input(text)
        if not is_valid:
            service = self.env['telegram.service'].sudo().with_context(bot_id=participant.bot_id.id).new()
            service.send_message(chat_id=participant.chat_id, text=validation_result)
            return {'success': False, 'error': validation_result}

        record = self.env[step.target_model_id.model].browse(participant.partner_id.id)
        record.write({step.target_field_id.name: text})

        participant._add_completed_field(f"{step.target_model_id.model}.{step.target_field_id.name}")

        return {'success': True}

    def handle_option_select(self, participant, step, message=None, is_restart=False):
        if is_restart and participant.is_step_completed(step):
            return {'success': True}
            
        buttons = [[{'text': option.text, 'callback_data': str(option.id)}] for option in step.option_ids]
        reply_markup = {'inline_keyboard': buttons}

        service = self.env['telegram.service'].sudo().with_context(bot_id=participant.bot_id.id).new()
        service.send_message(chat_id=participant.chat_id, text=step.content, reply_markup=reply_markup)

        return {'success': True, 'waiting_input': True}
