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
        """دریافت توکن ربات"""
        bot = self.env['telegram.bot'].browse(bot_id)
        if not bot or not bot.api_token:
            raise UserError('توکن API ربات یافت نشد')
        return bot._decrypt_token(bot.api_token)

    def send_message(self, chat_id, message, parse_mode='HTML', reply_markup=None, files=None):
        """ارسال پیام به تلگرام"""
        bot_id = self.env.context.get('bot_id')
        if not bot_id:
            raise UserError('شناسه ربات یافت نشد')
        
        token = self._get_bot_token(bot_id)
        
        # اگر نوع پیام پرداختی باشد، صورت‌حساب ارسال می‌شود
        step_id = self.env.context.get('step_id')
        if step_id:
            step = self.env['telegram.step'].browse(step_id)
            if step.message_type == 'payment':
                telegram_info = self.env['telegram.info'].search([('chat_id', '=', str(chat_id)), ('bot_id', '=', bot_id)], limit=1)
                if telegram_info:
                    partner = telegram_info.partner_id
                    payment = self.env['telegram.payment'].create({
                        'partner_id': partner.id,
                        'telegram_info_id': telegram_info.id,
                        'step_id': step.id,
                        'amount': step.price,
                        'currency': step.currency,
                        'state': 'draft',
                    })
                    return self.send_invoice(chat_id, step, payment)

        url = f'https://api.telegram.org/bot{token}/sendMessage'
        
        try:
            # حذف تگ‌های اضافی HTML
            if parse_mode == 'HTML':
                # حذف تگ p و data attributes
                message = re.sub(r'<p[^>]*>', '', message)
                message = message.replace('</p>', '')
                # حفظ تگ‌های مجاز HTML تلگرام
                allowed_tags = ['b', 'strong', 'i', 'em', 'u', 's', 'a', 'code', 'pre']
                for tag in allowed_tags:
                    message = message.replace(f'<{tag}>', f'<{tag}>')
                    message = message.replace(f'</{tag}>', f'</{tag}>')
                # حذف سایر تگ‌ها
                message = re.sub(r'<[^>]+>', '', message)

            data = {
                'chat_id': chat_id,
                'text': message,
                'parse_mode': parse_mode
            }

            if reply_markup:
                data['reply_markup'] = reply_markup

            _logger.info(f"Sending request to Telegram API: {data}")
            response = requests.post(url, json=data, timeout=10)
            response_data = response.json()
            
            # ثبت لاگ
            self._create_log(
                bot_id=bot_id,
                direction='outgoing',
                request_data=data,
                response_data=response_data,
                status_code=response.status_code,
                error=None if response_data.get('ok') else response_data.get('description')
            )

            if not response_data.get('ok'):
                error_msg = response_data.get('description', 'خطای ناشناخته')
                _logger.error(f"Telegram API error: {error_msg}")
                raise UserError(f"خطا از سمت تلگرام: {error_msg}")
            
            return response_data['result']
        
        except Exception as e:
            error_msg = str(e)
            # ثبت لاگ خطا
            self._create_log(
                bot_id=bot_id,
                direction='outgoing',
                request_data=data,
                response_data=None,
                status_code=500,
                error=error_msg
            )
            _logger.error(f"Error sending message: {error_msg}")
            raise UserError(f"خطا در ارسال پیام: {error_msg}")

    def _create_log(self, bot_id, direction, request_data=None, response_data=None, status_code=None, error=None):
        """ایجاد لاگ"""
        try:
            self.env['telegram.log'].sudo().create({
                'bot_id': bot_id,
                'direction': direction,
                'request_data': json.dumps(request_data, ensure_ascii=False) if request_data else None,
                'response_data': json.dumps(response_data, ensure_ascii=False) if response_data else None,
                'status_code': status_code,
                'error_message': error,
            })
        except Exception as e:
            _logger.error(f"خطا در ثبت لاگ: {str(e)}")

    def delete_webhook(self):
        """حذف webhook فعلی"""
        bot_id = self.env.context.get('bot_id')
        if not bot_id:
            raise UserError('شناسه ربات یافت نشد')
            
        token = self._get_bot_token(bot_id)
        url = f'https://api.telegram.org/bot{token}/deleteWebhook'
        
        try:
            _logger.info("در حال حذف webhook")
            response = requests.post(url, timeout=10)
            response_data = response.json()
            
            # ثبت لاگ
            self._create_log(
                bot_id=bot_id,
                direction='outgoing',
                request_data=None,
                response_data=response_data,
                status_code=response.status_code,
                error=None if response_data.get('ok') else response_data.get('description')
            )
            
            if not response_data.get('ok'):
                error_msg = response_data.get('description', 'خطای ناشناخته')
                _logger.error(f"خطا از تلگرام: {error_msg}")
                raise UserError(f"خطا از سمت تلگرام: {error_msg}")
            
            _logger.info("webhook با موفقیت حذف شد")
            return response_data
            
        except Exception as e:
            error_msg = str(e)
            # ثبت لاگ خطا
            self._create_log(
                bot_id=bot_id,
                direction='outgoing',
                request_data=None,
                response_data=None,
                status_code=500,
                error=error_msg
            )
            _logger.error(f"خطا در حذف webhook: {error_msg}", exc_info=True)
            raise UserError(f"خطا در حذف webhook: {error_msg}")

    def set_webhook(self, webhook_url):
        """تنظیم webhook جدید"""
        bot_id = self.env.context.get('bot_id')
        if not bot_id:
            raise UserError('شناسه ربات یافت نشد')
        
        token = self._get_bot_token(bot_id)
        url = f'https://api.telegram.org/bot{token}/setWebhook'
        
        data = {
            'url': webhook_url,
            'allowed_updates': ['message', 'callback_query', 'pre_checkout_query', 'successful_payment']
        }
        
        try:
            _logger.info(f"در حال تنظیم webhook به آدرس {webhook_url}")
            response = requests.post(url, json=data, timeout=10)
            response_data = response.json()
            
            # ثبت لاگ
            self._create_log(
                bot_id=bot_id,
                direction='outgoing',
                request_data=data,
                response_data=response_data,
                status_code=response.status_code,
                error=None if response_data.get('ok') else response_data.get('description')
            )
            
            if not response_data.get('ok'):
                error_msg = response_data.get('description', 'خطای ناشناخته')
                _logger.error(f"خطا از تلگرام: {error_msg}")
                raise UserError(f"خطا ازسمت تلگرام: {error_msg}")
            
            _logger.info(f"webhook با موفقیت تنظیم شد: {response_data}")
            return response_data
            
        except Exception as e:
            error_msg = str(e)
            # ثبت لاگ خطا
            self._create_log(
                bot_id=bot_id,
                direction='outgoing',
                request_data=data,
                response_data=None,
                status_code=500,
                error=error_msg
            )
            _logger.error(f"خطا در تنظیم webhook: {error_msg}", exc_info=True)
            raise UserError(f"خطا در تنظیم webhook: {error_msg}")

    def get_user_profile_photos(self, user_id):
        """دریافت تصاویر پروفایل کاربر"""
        bot_id = self.env.context.get('bot_id')
        if not bot_id:
            raise UserError('شناسه ربات یافت نشد')
        
        token = self._get_bot_token(bot_id)
        url = f'https://api.telegram.org/bot{token}/getUserProfilePhotos'
        
        params = {
            'user_id': user_id,
            'limit': 1  # فقط آخرین تصویر
        }
        
        try:
            response = requests.get(url, params=params, timeout=10)
            response_data = response.json()
            
            if not response_data.get('ok'):
                _logger.error(f"خطا در دریافت تصویر پروفایل: {response_data.get('description')}")
                return None
            
            photos = response_data.get('result', {}).get('photos', [])
            if not photos:
                return None
            
            # دریافت اطلاعات آخرین تصویر
            photo = photos[0][-1]  # بزرگترین سایز موجود
            file_content = self.get_file_content(photo['file_id'])
            if file_content:
                return base64.b64encode(file_content).decode('utf-8')
            return None
            
        except Exception as e:
            _logger.error(f"خطا در دریافت تصویر پروفایل: {str(e)}")
            return None

    def get_file_content(self, file_id):
        """دریافت محتوای فایل از تلگرام"""
        bot_id = self.env.context.get('bot_id')
        token = self._get_bot_token(bot_id)
        
        # دریافت مسیر فایل
        url = f'https://api.telegram.org/bot{token}/getFile'
        params = {'file_id': file_id}
        
        try:
            response = requests.get(url, params=params, timeout=10)
            response_data = response.json()
            
            if not response_data.get('ok'):
                return None
            
            file_path = response_data['result']['file_path']
            
            # دانلود فایل
            download_url = f'https://api.telegram.org/file/bot{token}/{file_path}'
            response = requests.get(download_url, timeout=10)
            
            if response.status_code == 200:
                return response.content
            
        except Exception as e:
            _logger.error(f"خطا در دریافت محتوی فایل: {str(e)}")
            
        return None

    def delete_message(self, chat_id, message_id):
        """حذف پیام از تلگرام"""
        return self._send_request('deleteMessage', {'chat_id': chat_id, 'message_id': message_id})

    def remove_keyboard(self, chat_id):
        """حذف کیبورد سفارشی"""
        return self.send_message(chat_id, '\u200B', reply_markup=json.dumps({'remove_keyboard': True}))

    def send_file(self, chat_id, file_content, filename, caption=None, parse_mode='HTML'):
        """ارسال انواع فایل به تلگرام"""
        if not file_content:
            raise ValueError('محتوای فایل خالی است')

        mime_type = mimetypes.guess_type(filename)[0] or 'application/octet-stream'
        file_data = base64.b64decode(file_content)

        params = {'chat_id': chat_id}
        if caption:
            params['caption'] = caption
        if parse_mode:
            params['parse_mode'] = parse_mode

        if mime_type.startswith('image/'):
            method = 'sendPhoto'
            files = {'photo': (filename, file_data, mime_type)}
        elif mime_type.startswith('video/'):
            method = 'sendVideo'
            files = {'video': (filename, file_data, mime_type)}
            params['supports_streaming'] = True
        elif mime_type.startswith('audio/'):
            method = 'sendAudio'
            files = {'audio': (filename, file_data, mime_type)}
        else:
            method = 'sendDocument'
            files = {'document': (filename, file_data, mime_type)}

        return self._send_request(method, params=params, files=files)

    def forward_message(self, chat_id, from_chat_id, message_id, disable_notification=None):
        """ارسال پیام فورواردی"""
        bot_id = self.env.context.get('bot_id')
        if not bot_id:
            raise UserError('شناسه ربات یافت نشد')
        
        token = self._get_bot_token(bot_id)
        url = f'https://api.telegram.org/bot{token}/forwardMessage'
        
        data = {
            'chat_id': chat_id,
            'from_chat_id': from_chat_id,
            'message_id': message_id
        }
        
        if disable_notification is not None:
            data['disable_notification'] = disable_notification
        
        try:
            response = requests.post(url, json=data, timeout=10)
            response_data = response.json()
            
            if not response_data.get('ok'):
                error_msg = response_data.get('description', 'خطای ناشناخته')
                raise UserError(f"خطا از سمت تلگرام: {error_msg}")
            
            return response_data
        
        except Exception as e:
            _logger.error(f"خطا در فوروارد پیام: {str(e)}")
            raise UserError(f"خطا در فوروارد پیام: {str(e)}")

    def send_invoice(self, chat_id, step, payment):
        """ارسال صورت‌حساب برای پرداخت"""
        bot_id = self.env.context.get('bot_id')
        if not bot_id:
            raise UserError('شناسه ربات یافت نشد')
            
        bot = self.env['telegram.bot'].browse(bot_id)
        token = self._get_bot_token(bot_id)
        
        if not bot.payment_provider_token:
            error_msg = 'توکن ارائه‌دهنده پرداخت برای این ربات تنظیم نشده است. لطفاً از طریق @BotFather یک ارائه‌دهنده پرداخت به ربات خود متصل کرده و توکن را در تنظیمات ربات در Odoo وارد کنید.'
            _logger.error(error_msg)
            raise UserError(error_msg)

        url = f'https://api.telegram.org/bot{token}/sendInvoice'
        
        prices = [{
            'label': step.name,
            'amount': int(step.price) if step.currency == 'XTR' else int(step.price * 100)
        }]
        
        payload = {
            'chat_id': chat_id,
            'title': step.name,
            'description': step.content or step.name,
            'payload': payment.name,
            'provider_token': bot.payment_provider_token,
            'currency': 'XTR' if step.currency == 'XTR' else 'USD',
            'prices': prices,
        }
        
        try:
            response = requests.post(url, json=payload, timeout=10)
            response_data = response.json()
            
            self._create_log(
                bot_id=bot_id,
                direction='outgoing',
                request_data=payload,
                response_data=response_data,
                status_code=response.status_code,
                error=None if response_data.get('ok') else response_data.get('description')
            )
            
            if not response_data.get('ok'):
                error_msg = response_data.get('description', 'خطای ناشناخته')
                raise UserError(f"خطا در ارسال صورت‌حساب: {error_msg}")
            
            payment.sudo().write({'message_id': response_data.get('result', {}).get('message_id')})
            return response_data['result']
        
        except Exception as e:
            error_msg = str(e)
            self._create_log(
                bot_id=bot_id,
                direction='outgoing',
                request_data=payload,
                response_data=None,
                status_code=500,
                error=error_msg
            )
            raise UserError(f"خطا در ارسال صورت‌حساب: {error_msg}")

    def answer_pre_checkout_query(self, pre_checkout_query_id, ok, error_message=None):
        """پاسخ به درخواست پیش از پرداخت"""
        bot_id = self.env.context.get('bot_id')
        if not bot_id:
            raise UserError('شناسه ربات یافت نشد')
            
        token = self._get_bot_token(bot_id)
        url = f'https://api.telegram.org/bot{token}/answerPreCheckoutQuery'
        
        payload = {
            'pre_checkout_query_id': pre_checkout_query_id,
            'ok': ok
        }
        
        if not ok and error_message:
            payload['error_message'] = error_message
            
        try:
            response = requests.post(url, json=payload, timeout=10)
            response_data = response.json()
            
            self._create_log(
                bot_id=bot_id,
                direction='outgoing',
                request_data=payload,
                response_data=response_data,
                status_code=response.status_code,
                error=None if response_data.get('ok') else response_data.get('description')
            )
            
            if not response_data.get('ok'):
                error_msg = response_data.get('description', 'خطای ناشناخته')
                raise UserError(f"خطا در پاسخ به پیش-پرداخت: {error_msg}")
            
            return response_data['result']
        
        except Exception as e:
            error_msg = str(e)
            self._create_log(
                bot_id=bot_id,
                direction='outgoing',
                request_data=payload,
                response_data=None,
                status_code=500,
                error=error_msg
            )
            raise UserError(f"خطا در پاسخ به پیش-پرداخت: {error_msg}")

    def copy_message(self, chat_id, from_chat_id, message_id, caption=None):
        """کپی پیام بدون منبع"""
        bot_id = self.env.context.get('bot_id')
        if not bot_id:
            raise UserError('شناسه ربات یافت نشد')
        
        token = self._get_bot_token(bot_id)
        url = f'https://api.telegram.org/bot{token}/copyMessage'
        
        data = {
            'chat_id': chat_id,
            'from_chat_id': from_chat_id,
            'message_id': message_id
        }
        
        if caption:
            data['caption'] = caption
        
        try:
            response = requests.post(url, json=data, timeout=10)
            response_data = response.json()
            
            if not response_data.get('ok'):
                error_msg = response_data.get('description', 'خطای ناشناخته')
                raise UserError(f"خطا از سمت تلگرام: {error_msg}")
            
            return response_data
        
        except Exception as e:
            _logger.error(f"خطا در کپی پیام: {str(e)}")
            raise UserError(f"خطا در کپی پیام: {str(e)}")

    def edit_message_text(self, chat_id, message_id, text, reply_markup=None):
        """ویرایش متن یک پیام"""
        bot_id = self.env.context.get('bot_id')
        if not bot_id:
            raise UserError('شناسه ربات یافت نشد')

        token = self._get_bot_token(bot_id)
        url = f'https://api.telegram.org/bot{token}/editMessageText'

        payload = {
            'chat_id': chat_id,
            'message_id': message_id,
            'text': text,
            'reply_markup': reply_markup
        }

        try:
            response = requests.post(url, json=payload, timeout=10)
            response_data = response.json()

            self._create_log(
                bot_id=bot_id,
                direction='outgoing',
                request_data=payload,
                response_data=response_data,
                status_code=response.status_code,
                error=None if response_data.get('ok') else response_data.get('description')
            )

            if not response_data.get('ok'):
                error_msg = response_data.get('description', 'خطای ناشناخته')
                _logger.error(f"خطا در ویرایش پیام: {error_msg}")

            return response_data

        except Exception as e:
            error_msg = str(e)
            self._create_log(
                bot_id=bot_id,
                direction='outgoing',
                request_data=payload,
                response_data=None,
                status_code=500,
                error=error_msg
            )
            _logger.error(f"خطا در ویرایش پیام: {error_msg}")
            return {'ok': False, 'error': error_msg}

    def edit_message_text(self, chat_id, message_id, text, reply_markup=None):
        """ویرایش متن یک پیام"""
        bot_id = self.env.context.get('bot_id')
        if not bot_id:
            raise UserError('شناسه ربات یافت نشد')

        token = self._get_bot_token(bot_id)
        url = f'https://api.telegram.org/bot{token}/editMessageText'

        payload = {
            'chat_id': chat_id,
            'message_id': message_id,
            'text': text,
        }
        if reply_markup:
            payload['reply_markup'] = reply_markup

        try:
            response = requests.post(url, json=payload, timeout=10)
            response_data = response.json()

            self._create_log(
                bot_id=bot_id,
                direction='outgoing',
                request_data=payload,
                response_data=response_data,
                status_code=response.status_code,
                error=None if response_data.get('ok') else response_data.get('description')
            )

            if not response_data.get('ok'):
                error_msg = response_data.get('description', 'خطای ناشناخته')
                _logger.error(f"خطا در ویرایش پیام: {error_msg}")

            return response_data

        except Exception as e:
            error_msg = str(e)
            self._create_log(
                bot_id=bot_id,
                direction='outgoing',
                request_data=payload,
                response_data=None,
                status_code=500,
                error=error_msg
            )
            _logger.error(f"خطا در ویرایش پیام: {error_msg}")
            return {'ok': False, 'error': error_msg}


    def process_step(self, step, telegram_info, message=None):
        """پردازش مرحله"""
        service = self.with_context(bot_id=telegram_info.bot_id.id)

        if step.message_type == 'text':
            if step.attachment:
                return service.send_file(telegram_info.chat_id, step.attachment, step.attachment_name, caption=step.content)
            else:
                return service.send_message(telegram_info.chat_id, step.content)

        elif step.message_type == 'forward':
            return service.process_forward_message(step, telegram_info)

        elif step.message_type == 'save_info':
            if not message:
                return service.send_message(telegram_info.chat_id, step.content or 'لطفاً اطلاعات را وارد کنید')
            else:
                is_valid, validation_result = step.validate_input(message)
                if not is_valid:
                    service.send_message(telegram_info.chat_id, validation_result if isinstance(validation_result, str) else 'خطای نامشخص')
                    return {'error': validation_result}

                if step.target_model_id and step.target_field_id:
                    model = self.env[step.target_model_id.model]
                    record = model.browse(telegram_info.partner_id.id)
                    record.write({step.target_field_id.name: message})

                return {'success': True}

        # ... (add other message types here)

        return False

    def process_forward_message(self, step, telegram_info):
        """پردازش پیام فورواردی"""
        if not step.forward_link:
            return False

        parts = step.forward_link.split('/')
        if len(parts) < 2:
            return False

        channel_name = parts[-2].replace('@', '')
        message_id = int(parts[-1])

        service = self.with_context(bot_id=telegram_info.bot_id.id)

        try:
            if step.forward_with_source:
                result = service.forward_message(telegram_info.chat_id, f"@{channel_name}", message_id)
            else:
                result = service.copy_message(telegram_info.chat_id, f"@{channel_name}", message_id)

            if result and step.delete_after:
                self.env['telegram.message.delete'].create({
                    'chat_id': telegram_info.chat_id,
                    'message_id': result['result']['message_id'],
                    'bot_id': telegram_info.bot_id.id,
                    'step_id': step.id,
                    'delete_time': fields.Datetime.now() + timedelta(minutes=step.delete_delay)
                })
            return result
        except Exception as e:
            _logger.error(f"خطا در پردازش پیام فورواردی: {str(e)}")
            if step.content:
                return service.send_message(telegram_info.chat_id, step.content)
            return False

    def _send_request(self, method, params=None, files=None, is_json=False):
        """ارسال درخواست به API تلگرام"""
        bot_id = self.env.context.get('bot_id')
        if not bot_id:
            raise UserError('شناسه ربات یافت نشد')
        
        token = self._get_bot_token(bot_id)
        url = f'https://api.telegram.org/bot{token}/{method}'
        
        try:
            if is_json:
                response = requests.post(url, json=params, timeout=10)
            else:
                response = requests.post(url, data=params, files=files, timeout=10)

            response_data = response.json()
            
            self._create_log(
                bot_id=bot_id,
                direction='outgoing',
                request_data=params,
                response_data=response_data,
                status_code=response.status_code,
                error=None if response_data.get('ok') else response_data.get('description')
            )
            
            if not response_data.get('ok'):
                error_msg = response_data.get('description', 'خطای ناشناخته')
                _logger.error(f"Telegram API error: {error_msg}")
                raise UserError(f"خطا از سمت تلگرام: {error_msg}")
            
            return response_data.get('result')
            
        except Exception as e:
            error_msg = str(e)
            self._create_log(
                bot_id=bot_id,
                direction='outgoing',
                request_data=params,
                response_data=None,
                status_code=500,
                error=error_msg
            )
            _logger.error(f"Error in API request: {error_msg}")
            raise UserError(f"خطا در ارسال درخواست: {error_msg}")