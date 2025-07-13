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
    bot_start_date = fields.Datetime(string='تاریخ شروع', default=fields.Datetime.now, readonly=True)
    last_interaction_date = fields.Datetime(string='آخرین تعامل', default=fields.Datetime.now)

    name = fields.Char(related='partner_id.name', string='نام', store=True)
    phone = fields.Char(related='partner_id.phone', string='تلفن', store=True)
    mobile = fields.Char(related='partner_id.mobile', string='موبایل', store=True)
    email = fields.Char(related='partner_id.email', string='ایمیل', store=True)

    _sql_constraints = [
        ('unique_partner_bot_telegram',
         'UNIQUE(partner_id, bot_id, telegram_id)',
         'این کاربر قبلاً برای این ربات با این شناسه تلگرام ثبت شده است!')
    ]

    def process_start_parameter(self, start_parameter):
        """پردازش پارامتر شروع و شروع کمپین"""
        _logger = logging.getLogger(__name__)
        _logger.info(f"Processing start parameter: {start_parameter}")
        
        try:
            # جستجوی کمپین فعال
            campaign = self.env['telegram.campaign'].sudo().search([
                ('start_parameter', '=', start_parameter),
                ('bot_id', '=', self.bot_id.id),
                ('state', '=', 'active')
            ], limit=1)
            
            if not campaign:
                _logger.warning(f"Campaign not found for start parameter: {start_parameter}")
                return False

            _logger.info(f"Campaign found: {campaign.name}")

            # یافتن یا ایجاد شرکت‌کننده
            participant, created = self.env['telegram.campaign.participant'].sudo().find_or_create(self, campaign)

            if created:
                _logger.info(f"Participant created with ID: {participant.id}")
            else:
                _logger.info(f"Participant found: {participant.id}")
                participant.write({'last_start_date': fields.Datetime.now()})

            # ارسال پیام های خوانده نشده
            steps_to_send = self.env['telegram.step']
            for step in campaign.step_ids.sorted(lambda s: s.sequence):
                if step.message_type in ['text', 'forward']:
                    steps_to_send |= step
                else:
                    if not participant.is_step_completed(step):
                        steps_to_send |= step
                        break

            for step in steps_to_send:
                participant.process_step(step)

            return True
            
        except Exception as e:
            _logger.error(f'خطا در پردازش پارامتر شروع {start_parameter}: {str(e)}')
            return False
