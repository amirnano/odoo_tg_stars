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
            if request.httprequest.method == 'GET':
                return Response(
                    json.dumps({
                        'ok': False,
                        'message': 'این آدرس فقط برای دریافت webhook تلگرام است و نباید مستقیماً فراخوانی شود.'
                    }),
                    content_type='application/json',
                    status=405
                )

            bot = request.env['telegram.bot'].sudo().browse(bot_id)
            if not bot or not bot.is_active:
                return Response(status=403)

            if not self._check_rate_limit(str(bot_id)):
                return Response(status=429)

            data = request.httprequest.get_data()
            if not data:
                return Response(status=400)
            
            data = json.loads(data)
            if not isinstance(data, dict):
                return Response(status=400)

            result = self._process_message(bot, data)
            
            self._log_request(bot, data, result)
            
            return Response(
                json.dumps({'ok': True}), 
                content_type='application/json'
            )

        except Exception as e:
            _logger.error(f"Error processing webhook: {str(e)}", exc_info=True)
            self._log_request(bot, data, {'error': str(e)})
            return Response(
                json.dumps({'ok': False, 'error': str(e)}),
                content_type='application/json',
                status=400
            )

    def _log_request(self, bot, data, result=None):
        try:
            response_data = result
            if isinstance(result, Response):
                response_data = {'status_code': result.status_code}

            request.env['telegram.log'].sudo().create({
                'bot_id': bot.id,
                'direction': 'incoming',
                'request_data': json.dumps(data, ensure_ascii=False) if data else None,
                'response_data': json.dumps(response_data, ensure_ascii=False) if response_data else None,
                'status_code': 200
            })
        except Exception as e:
            _logger.error(f"خطا در ثبت لاگ درخواست: {str(e)}")

    def _process_message(self, bot, data):
        _logger.info(f"Processing message with data: {data}")
        
        message = data.get('message', {})
        pre_checkout_query = data.get('pre_checkout_query')
        callback_query = data.get('callback_query')

        if pre_checkout_query:
            user_data = pre_checkout_query.get('from', {})
        elif callback_query:
            user_data = callback_query.get('from', {})
        else:
            user_data = message.get('from', {})
        
        telegram_id = user_data.get('id')
        
        telegram_info = request.env['telegram.info'].sudo().search([('telegram_id', '=', str(telegram_id)), ('bot_id', '=', bot.id)], limit=1)
        if not telegram_info:
            partner = request.env['res.partner'].sudo().search([('telegram_info_ids.telegram_id', '=', str(telegram_id))], limit=1)
            if not partner:
                partner = request.env['res.partner'].sudo().create({
                    'name': user_data.get('first_name', '') + ' ' + user_data.get('last_name', ''),
                })
            telegram_info = request.env['telegram.info'].sudo().create({
                'partner_id': partner.id,
                'bot_id': bot.id,
                'telegram_id': str(telegram_id),
                'telegram_username': user_data.get('username'),
                'chat_id': message.get('chat', {}).get('id'),
            })

        if message.get('successful_payment'):
            return self._process_successful_payment(bot, message.get('successful_payment'))

        if pre_checkout_query:
            return self._process_pre_checkout_query(bot, pre_checkout_query)

        if callback_query:
            return self._process_callback_query(bot, callback_query)

        text = message.get('text', '')
        if text.startswith('/start'):
            return self._process_start_command(bot, message)
        
        participant = request.env['telegram.campaign.participant'].sudo().search([
            ('telegram_info_id', '=', telegram_info.id),
            ('state', '=', 'active')
        ], order='last_start_date desc', limit=1)
        
        if participant:
            participant.process_step(participant.current_step_id, message)
        else:
            service = request.env['telegram.service'].sudo().with_context(bot_id=bot.id).new()
            service.send_message(chat_id=telegram_info.chat_id, message="درخواست نامعتبر")

        return Response(status=200)

    def _process_start_command(self, bot, message):
        text = message.get('text', '')
        parts = text.split()
        if len(parts) > 1:
            start_parameter = parts[1]
            campaign = request.env['telegram.campaign'].sudo().search([
                ('start_parameter', '=', start_parameter),
                ('bot_id', '=', bot.id),
                ('state', '=', 'active')
            ], limit=1)
            if campaign:
                telegram_info = request.env['telegram.info'].sudo().search([('telegram_id', '=', str(message['from']['id'])), ('bot_id', '=', bot.id)], limit=1)
                participant, created = request.env['telegram.campaign.participant'].sudo().find_or_create(telegram_info, campaign)
                if not created:
                    participant.write({'last_start_date': datetime.now()})

                steps_to_send = request.env['telegram.step']
                for step in campaign.step_ids.sorted('sequence'):
                    if not participant.is_step_completed(step):
                        steps_to_send |= step
                        if step.message_type not in ['text', 'forward']:
                            break

                for step in steps_to_send:
                    participant.process_step(step)
            else:
                service = request.env['telegram.service'].sudo().with_context(bot_id=bot.id).new()
                service.send_message(chat_id=message['chat']['id'], message="کمپین یافت نشد")
        else:
            service = request.env['telegram.service'].sudo().with_context(bot_id=bot.id).new()
            service.send_message(chat_id=message['chat']['id'], message=bot.welcome_message or 'خوش آمدید!')
        return Response(status=200)

    def _process_successful_payment(self, bot, successful_payment):
        invoice_payload = successful_payment['invoice_payload']
        payment = request.env['telegram.payment'].sudo().search([('name', '=', invoice_payload)], limit=1)
        if not payment:
            return Response(status=400)

        payment.write({
            'state': 'paid',
            'telegram_charge_id': successful_payment['telegram_payment_charge_id'],
            'provider_charge_id': successful_payment['provider_payment_charge_id'],
        })

        participant = request.env['telegram.campaign.participant'].sudo().search([
            ('telegram_info_id', '=', payment.telegram_info_id.id),
            ('campaign_id', '=', payment.step_id.campaign_id.id)
        ], limit=1)
        
        if participant:
            service = request.env['telegram.service'].sudo().with_context(bot_id=bot.id).new()
            service.edit_message_text(
                chat_id=participant.chat_id,
                message_id=payment.message_id,
                text=f"✅ پرداخت شما برای {payment.step_id.name} با موفقیت انجام شد.",
            )

            steps_to_send = request.env['telegram.step']
            for step in participant.campaign_id.step_ids.filtered(lambda s: s.sequence > payment.step_id.sequence).sorted('sequence'):
                if not participant.is_step_completed(step):
                    steps_to_send |= step
                    if step.message_type not in ['text', 'forward']:
                        break

            for step in steps_to_send:
                participant.process_step(step)

        return Response(status=200)

    def _process_pre_checkout_query(self, bot, pre_checkout_query):
        payment = request.env['telegram.payment'].sudo().search([('name', '=', pre_checkout_query['invoice_payload'])], limit=1)
        service = request.env['telegram.service'].sudo().with_context(bot_id=bot.id).new()
        if payment:
            service.answer_pre_checkout_query(pre_checkout_query['id'], ok=True)
        else:
            service.answer_pre_checkout_query(pre_checkout_query['id'], ok=False, error_message="پرداخت یافت نشد")
        return Response(status=200)

    def _process_callback_query(self, bot, callback_query):
        participant = request.env['telegram.campaign.participant'].sudo().search([
            ('telegram_info_id.telegram_id', '=', str(callback_query['from']['id'])),
            ('bot_id', '=', bot.id)
        ], order='last_start_date desc', limit=1)

        if participant:
            participant.process_option_selection(callback_query['data'], callback_query['message'])

        service = request.env['telegram.service'].sudo().with_context(bot_id=bot.id).new()
        service.answer_callback_query(callback_query['id'])
        return Response(status=200)
