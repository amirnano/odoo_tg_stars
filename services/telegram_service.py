import logging
import requests
from odoo import models
from odoo.exceptions import UserError
import json
import base64
import tempfile
import os
import mimetypes
import re

_logger = logging.getLogger(__name__)

class TelegramService(models.AbstractModel):
    _name = 'telegram.service'
    _description = 'سرویس تلگرام'

    def _get_bot_token(self, bot_id):
        bot = self.env['telegram.bot'].browse(bot_id)
        if not bot or not bot.api_token:
            raise UserError('توکن API ربات یافت نشد')
        return bot._decrypt_token(bot.api_token)

    def _send_request(self, method, params=None, files=None):
        bot_id = self.env.context.get('bot_id')
        if not bot_id:
            raise UserError('شناسه ربات یافت نشد')
        
        token = self._get_bot_token(bot_id)
        url = f'https://api.telegram.org/bot{token}/{method}'
        
        try:
            response = requests.post(url, data=params, files=files, timeout=10)
            response_data = response.json()
            
            self.env['telegram.log'].sudo().create({
                'bot_id': bot_id,
                'direction': 'outgoing',
                'request_data': json.dumps(params, ensure_ascii=False) if params else None,
                'response_data': json.dumps(response_data, ensure_ascii=False) if response_data else None,
                'status_code': response.status_code,
                'error_message': None if response_data.get('ok') else response_data.get('description')
            })
            
            if not response_data.get('ok'):
                _logger.error(f"Telegram API error: {response_data.get('description')}")
            
            return response_data
            
        except Exception as e:
            _logger.error(f"Error in API request: {str(e)}")
            self.env['telegram.log'].sudo().create({
                'bot_id': bot_id,
                'direction': 'outgoing',
                'request_data': json.dumps(params, ensure_ascii=False) if params else None,
                'response_data': None,
                'status_code': 500,
                'error_message': str(e)
            })
            return {'ok': False, 'error': str(e)}

    def send_message(self, chat_id, text, parse_mode='HTML', reply_markup=None):
        params = {'chat_id': chat_id, 'text': text, 'parse_mode': parse_mode}
        if reply_markup:
            params['reply_markup'] = json.dumps(reply_markup)
        return self._send_request('sendMessage', params=params)

    def send_invoice(self, chat_id, step, payment):
        bot_id = self.env.context.get('bot_id')
        bot = self.env['telegram.bot'].browse(bot_id)
        if not bot.payment_provider_token:
            raise UserError('توکن ارائه‌دهنده پرداخت برای این ربات تنظیم نشده است.')

        prices = [{'label': step.name, 'amount': int(step.price) if step.currency == 'XTR' else int(step.price * 100)}]
        
        params = {
            'chat_id': chat_id,
            'title': step.name,
            'description': step.content or step.name,
            'payload': payment.name,
            'provider_token': bot.payment_provider_token,
            'currency': 'XTR' if step.currency == 'XTR' else 'USD',
            'prices': json.dumps(prices),
        }
        
        response = self._send_request('sendInvoice', params=params)
        if response.get('ok'):
            payment.sudo().write({'message_id': response.get('result', {}).get('message_id')})
        return response

    def answer_pre_checkout_query(self, pre_checkout_query_id, ok, error_message=None):
        params = {'pre_checkout_query_id': pre_checkout_query_id, 'ok': ok}
        if not ok and error_message:
            params['error_message'] = error_message
        return self._send_request('answerPreCheckoutQuery', params=params)

    def answer_callback_query(self, callback_query_id, text=None, show_alert=False):
        params = {'callback_query_id': callback_query_id, 'show_alert': show_alert}
        if text:
            params['text'] = text
        return self._send_request('answerCallbackQuery', params=params)

    def edit_message_text(self, chat_id, message_id, text, reply_markup=None):
        params = {'chat_id': chat_id, 'message_id': message_id, 'text': text}
        if reply_markup:
            params['reply_markup'] = json.dumps(reply_markup)
        return self._send_request('editMessageText', params=params)

    def remove_keyboard(self, chat_id):
        return self.send_message(chat_id, '\u200B', reply_markup={'remove_keyboard': True})
