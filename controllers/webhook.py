import logging
import json
from datetime import datetime, timedelta
from odoo import http
from odoo.http import request, Response
from werkzeug.exceptions import BadRequest, TooManyRequests
from odoo.exceptions import ValidationError
import redis
import requests

_logger = logging.getLogger(__name__)

class WebhookController(http.Controller):
    def __init__(self):
        super().__init__()
        self.redis_client = redis.Redis(host='localhost', port=6379, db=0)
        
    def _check_rate_limit(self, token):
        """محدودیت تعداد درخواست"""
        key = f"rate_limit:{token}"
        current = int(self.redis_client.get(key) or 0)
        if current >= 100:  # محدودیت 100 درخواست در دقیقه
            return False
        self.redis_client.incr(key)
        self.redis_client.expire(key, 60)  # منقضی شدن بعد از 60 ثانیه
        return True
        
    @http.route('/telegram/webhook/<int:bot_id>', type='http', auth='public', csrf=False, methods=['GET', 'POST'])
    def telegram_webhook(self, bot_id, **kwargs):
        try:
            # اگر متد GET ب
            if request.httprequest.method == 'GET':
                return Response(
                    json.dumps({
                        'ok': False,
                        'message': 'این آدرس فقط برای دریافت webhook تلگرام است و نباید مستقیماً فراخوانی شود.'
                    }),
                    content_type='application/json',
                    status=405
                )

            # اعتبارسنجی ربات
            bot = request.env['telegram.bot'].sudo().browse(bot_id)
            if not bot or not bot.is_active:
                return Response(status=403)

            # بررسی rate limit
            if not self._check_rate_limit(str(bot_id)):
                return Response(status=429)

            # دریافت و اعتبارسنجی داده
            data = request.httprequest.get_data()
            if not data:
                return Response(status=400)
            
            data = json.loads(data)
            if not isinstance(data, dict):
                return Response(status=400)

            # پردازش پیام
            result = self._process_message(bot, data)
            
            # ثبت لاگ درخواست و پاسخ در یک رکورد
            self._log_request(bot, data, result)
            
            return Response(
                json.dumps({'ok': True}), 
                content_type='application/json'
            )

        except Exception as e:
            _logger.error(f"Error processing webhook: {str(e)}", exc_info=True)
            # ثبت لاگ خطا
            self._log_request(bot, data, {'error': str(e)})
            return Response(
                json.dumps({'ok': False, 'error': str(e)}),
                content_type='application/json',
                status=400
            )

    def _log_request(self, bot, data, result=None):
        """ثبت لاگ درخواست و پاسخ در یک رکورد"""
        try:
            response_data = result
            if isinstance(result, Response):
                response_data = {'status_code': result.status_code}

            return request.env['telegram.log'].sudo().create({
                'bot_id': bot.id,
                'direction': 'incoming',
                'request_data': json.dumps(data, ensure_ascii=False) if data else None,
                'response_data': json.dumps(response_data, ensure_ascii=False) if response_data else None,
                'status_code': 200
            })
        except Exception as e:
            _logger.error(f"خطا در ثبت لاگ درخواست: {str(e)}")
            return False

    def _log_response(self, bot, result, status_code=200):
        """ثبت لاگ پاسخ"""
        try:
            return request.env['telegram.log'].sudo().create({
                'bot_id': bot.id,
                'direction': 'outgoing',
                'response_data': json.dumps(result, ensure_ascii=False),
                'status_code': status_code,
                'error_message': result.get('error')
            })
        except Exception as e:
            _logger.error(f"خطا در ثبت لاگ پاسخ: {str(e)}")
            return False

    def _process_message(self, bot, data):
        """پردازش پیام دریافتی"""
        _logger = logging.getLogger(__name__)
        _logger.info(f"Processing message with data: {data}")
        
        try:
            message = data.get('message', {})
            pre_checkout_query = data.get('pre_checkout_query')
            if pre_checkout_query:
                user_data = pre_checkout_query.get('from', {})
            else:
                user_data = message.get('from', {})
            
            chat_id = message.get('chat', {}).get('id')
            telegram_id = user_data.get('id')
            username = user_data.get('username')
            first_name = user_data.get('first_name', '')
            last_name = user_data.get('last_name', '')
            is_premium = user_data.get('is_premium', False)

            _logger.info(f"Telegram ID: {telegram_id}, Bot ID: {bot.id}")

            # یافتن یا ایجاد کاربر
            telegram_info_search = request.env['telegram.info'].sudo().search([('telegram_id', '=', str(telegram_id))], limit=1)
            partner = telegram_info_search.partner_id if telegram_info_search else None
            if not partner:
                # ایجاد مخاطب جدید
                _logger.info(f"Creating new partner for {username}")
                
                # دریافت یا ایجاد دسته‌بندی Premium
                premium_category = request.env['res.partner.category'].sudo().search([
                    ('name', '=', 'Premium')
                ], limit=1)
                
                if not premium_category:
                    premium_category = request.env['res.partner.category'].sudo().create({
                        'name': 'Premium'
                    })
                
                # ایجاد مخاطب بایگانی شده
                partner_vals = {
                    'name': f"{first_name} {last_name}".strip() or username or str(telegram_id),
                    'active': False,  # بایگانی شده
                }
                
                # اضافه کردن برچسب Premium برای کاربران premium
                if is_premium:
                    partner_vals['category_id'] = [(4, premium_category.id)]
                
                # دریافت تصویر پروفایل
                service = request.env['telegram.service'].sudo().with_context(bot_id=bot.id).new()
                profile_photo = service.get_user_profile_photos(telegram_id)
                if profile_photo:
                    partner_vals['image_1920'] = profile_photo
                
                partner = request.env['res.partner'].sudo().create(partner_vals)
                _logger.info(f"Partner created with ID: {partner.id}")

            telegram_info = request.env['telegram.info'].sudo().search([('telegram_id', '=', str(telegram_id)), ('bot_id', '=', bot.id)], limit=1)
            if not telegram_info:
                telegram_info = request.env['telegram.info'].sudo().create({
                    'partner_id': partner.id,
                    'bot_id': bot.id,
                    'telegram_id': str(telegram_id),
                    'telegram_username': username,
                    'chat_id': str(chat_id),
                })
                _logger.info(f"Telegram Info created with ID: {telegram_info.id}")
            else:
                telegram_info.write({'last_interaction_date': datetime.now()})
                _logger.info(f"Telegram Info found with ID: {telegram_info.id}")

            # بررسی اشتراک‌گذاری مخاطب
            contact = message.get('contact')
            text = message.get('text', '')
            
            _logger.info(f"پیام دریافتی: {text} از کاربر {username} با chat_id {chat_id}")
            
            # بررسی callback_query برای گزینه‌ها
            successful_payment = message.get('successful_payment')
            if successful_payment:
                return self._process_successful_payment(bot, successful_payment)

            pre_checkout_query = data.get('pre_checkout_query')
            if pre_checkout_query:
                return self._process_pre_checkout_query(bot, pre_checkout_query)

            callback_query = data.get('callback_query')
            if callback_query:
                _logger.info(f"Received callback query: {callback_query}")
                message = callback_query.get('message', {})
                chat_id = message.get('chat', {}).get('id')
                telegram_id = callback_query['from'].get('id')
                callback_data = callback_query.get('data', '')
                
                env = request.env(context={'telegram_user_id': telegram_id})
                participant = env['telegram.campaign.participant'].sudo().search([
                    ('telegram_info_id.telegram_id', '=', str(telegram_id)),
                    ('bot_id', '=', bot.id)
                ], order='last_start_date desc', limit=1)
                
                if participant:
                    result = participant.process_option_selection(callback_data, message)
                    
                    # پاسخ به callback_query
                    answer_url = f'https://api.telegram.org/bot{bot._decrypt_token(bot.api_token)}/answerCallbackQuery'
                    requests.post(answer_url, json={
                        'callback_query_id': callback_query['id']
                    })
                    
                    return result

            # بررسی دستور start و پارامتر آن
            if text and text.startswith('/start'):
                parts = text.split()
                start_parameter = parts[1] if len(parts) > 1 else None

                if not start_parameter and message.get('entities'):
                    for entity in message['entities']:
                        if entity['type'] == 'bot_command':
                            command_text = text[entity['offset']:entity['offset'] + entity['length']]
                            if command_text == '/start':
                                start_parameter = text[entity['offset'] + entity['length']:].strip()
                                break
                
                if start_parameter:
                    telegram_info.process_start_parameter(start_parameter)
                else:
                    service = request.env['telegram.service'].sudo().with_context(bot_id=bot.id).new()
                    service.send_message(
                        chat_id=chat_id,
                        message=bot.welcome_message or 'خوش آمدید!'
                    )
                
                return Response(status=200)
            
            # پردازش پیام‌های عادی
            participant = request.env['telegram.campaign.participant'].sudo().search([
                ('telegram_info_id', '=', telegram_info.id)
            ], order='last_start_date desc', limit=1)

            if participant and participant.current_step_id:
                current_step = participant.current_step_id
                if current_step.message_type == 'payment':
                    # اگر نوع پیام پرداختی است، منتظر پاسخ پرداخت می‌مانیم و کاری انجام نمی‌دهیم
                    return Response(status=200)

                if contact:
                    # اگر مخاطب به اشتراک گذاشته شده
                    phone = contact.get('phone_number')
                    contact_user_id = contact.get('user_id')
                    
                    # بررسی اینکه آیا شماره متعلق به خود کاربر است
                    if str(contact_user_id) != str(telegram_id):
                        service = request.env['telegram.service'].sudo().with_context(bot_id=bot.id).new()
                        service.send_message(
                            chat_id=str(chat_id),
                            message='لطفاً شماره تماس خود را به اشتراک بگذارید'
                        )
                        return Response(status=200)
                    
                    if phone and participant.current_step_id:
                        contact_data = {
                            'phone_number': phone,
                            'user_id': telegram_id
                        }
                        
                        # پردازش شماره تماس
                        participant.process_step(
                            participant.current_step_id,
                            contact_data
                        )
                        
                        # حذف کیبورد با ارسال یک کیبورد خالی
                        service = request.env['telegram.service'].sudo().with_context(bot_id=bot.id).new()
                        service.remove_keyboard(chat_id)
                        
                        return Response(status=200)
                        
                    else:
                        service = request.env['telegram.service'].sudo().with_context(bot_id=bot.id).new()
                        service.send_message(
                            chat_id=str(chat_id),
                            message='لطفاً شماره تماس خود را به اشتراک بگذارید'
                        )
                        return Response(status=200)
                elif text:
                    # پردازش پیام متنی
                    participant.process_step(
                        participant.current_step_id,
                        text
                    )
                    return Response(status=200)
            
            # اگر هیچ یک از موارد بالا نبود، پیام نامعتبر است
            service = request.env['telegram.service'].sudo().with_context(bot_id=bot.id).new()
            service.send_message(
                chat_id=chat_id,
                message='درخواست شما نامعتبر است.'
            )
            return Response(status=200)

        except Exception as e:
            _logger.error(f"خطا در پردازش پیام: {str(e)}", exc_info=True)
            return Response(status=500)

    def _process_start_command(self, bot, message, start_param):
        """پردازش دستور start"""
        chat_id = message['chat']['id']
        telegram_id = message['from']['id']
        
        # یافتن کمپین مرتبط
        campaign = request.env['telegram.campaign'].sudo().search([
            ('start_parameter', '=', start_param),
            ('bot_id', '=', bot.id),
            ('state', '=', 'active')
        ], limit=1)
        
        if not campaign:
            return False

        # یافتن یا ایجاد مخاطب
        partner = self._get_or_create_partner(message)
        if not partner:
            return False

        # یافتن یا ایجاد اطلاعات تلگرام
        telegram_info = request.env['telegram.info'].sudo().search([
            ('partner_id', '=', partner.id),
            ('bot_id', '=', bot.id),
            ('telegram_id', '=', str(telegram_id))
        ], limit=1)

        if telegram_info:
            # ایجاد رکورد جدید برای کمپین جدید
            telegram_info = telegram_info.join_campaign(campaign)
        else:
            # ایجاد رکورد جدید
            telegram_info = request.env['telegram.info'].sudo().create({
                'partner_id': partner.id,
                'bot_id': bot.id,
                'telegram_id': str(telegram_id),
                'telegram_username': message['from'].get('username', ''),
                'chat_id': str(chat_id),
                'campaign_id': campaign.id,
                'campaign_join_date': fields.Datetime.now(),
            })

        _logger.info(f"کاربر {chat_id} به کمپین {campaign.name} پیوست")
        return telegram_info

    def _process_pre_checkout_query(self, bot, pre_checkout_query):
        """پردازش درخواست پیش از پرداخت"""
        query_id = pre_checkout_query['id']
        invoice_payload = pre_checkout_query['invoice_payload']
        
        payment = request.env['telegram.payment'].sudo().search([('name', '=', invoice_payload)], limit=1)
        
        service = request.env['telegram.service'].sudo().with_context(bot_id=bot.id).new()

        if not payment:
            # ارسال پاسخ منفی
            service.answer_pre_checkout_query(query_id, ok=False, error_message='پرداخت یافت نشد')
            return Response(status=400)

        # ارسال پاسخ مثبت
        service.answer_pre_checkout_query(query_id, ok=True)
        return Response(status=200)

    def _process_successful_payment(self, bot, successful_payment):
        """پردازش پرداخت موفق"""
        _logger.info(f"Processing successful payment: {successful_payment}")
        invoice_payload = successful_payment['invoice_payload']
        telegram_charge_id = successful_payment['telegram_payment_charge_id']
        provider_charge_id = successful_payment['provider_payment_charge_id']

        payment = request.env['telegram.payment'].sudo().search([('name', '=', invoice_payload)], limit=1)

        if not payment:
            _logger.error(f"Payment not found for invoice payload: {invoice_payload}")
            return Response(status=400)

        payment.write({
            'state': 'paid',
            'telegram_charge_id': telegram_charge_id,
            'provider_charge_id': provider_charge_id,
        })
        _logger.info(f"Payment {payment.id} marked as paid.")

        # انتقال به مرحله بعد
        participant = request.env['telegram.campaign.participant'].sudo().search([
            ('telegram_info_id', '=', payment.telegram_info_id.id),
            ('campaign_id', '=', payment.step_id.campaign_id.id)
        ], limit=1)
        
        if participant:
            _logger.info(f"Participant {participant.id} found for payment.")
            current_step = payment.step_id

            # Edit the original invoice message
            service = request.env['telegram.service'].sudo().with_context(bot_id=bot.id).new()
            service.edit_message_text(
                chat_id=participant.chat_id,
                message_id=payment.message_id,
                text=f"✅ پرداخت شما برای {current_step.name} با موفقیت انجام شد.",
                reply_markup=None
            )

            steps_to_send = request.env['telegram.step']
            for step in participant.sudo().campaign_id.step_ids.filtered(lambda s: s.sequence > current_step.sequence).sorted(lambda s: s.sequence):
                if step.message_type in ['text', 'forward']:
                    steps_to_send |= step
                else:
                    steps_to_send |= step
                    if step.message_type not in ['text', 'forward']:
                        break

            for step in steps_to_send:
                participant.process_step(step)
        else:
            _logger.error(f"No participant found for payment {payment.id}")

        return Response(status=200)
