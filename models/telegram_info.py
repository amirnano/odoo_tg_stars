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
        
        try:
            # جستجوی کمپین فعال
            campaign = self.env['telegram.campaign'].sudo().search([
                ('start_parameter', '=', start_parameter),
                ('bot_id', '=', self.bot_id.id),
                ('state', '=', 'active')
            ], limit=1)
            
            if not campaign:
                return False

            # یافتن یا ایجاد شرکت‌کننده
            participant = self.env['telegram.campaign.participant'].sudo().search([
                ('telegram_info_id', '=', self.id),
                ('campaign_id', '=', campaign.id)
            ], limit=1)

            if participant:
                # اگر کاربر قبلاً در کمپین شرکت کرده، از مرحله فعلی ادامه می‌دهیم
                participant.write({'last_start_date': fields.Datetime.now()})
                first_step = participant.current_step_id or campaign.step_ids.sorted(lambda s: s.sequence)[:1]
                if first_step:
                    return participant.process_step(first_step)
                return True
            else:
                # ثبت شرکت‌کننده جدید در کمپین
                participant = self.env['telegram.campaign.participant'].sudo().create({
                    'campaign_id': campaign.id,
                    'telegram_info_id': self.id,
                    'join_date': fields.Datetime.now(),
                    'last_start_date': fields.Datetime.now(),
                    'partner_id': self.partner_id.id,
                    'telegram_id': self.telegram_id,
                    'telegram_username': self.telegram_username,
                    'chat_id': self.chat_id,
                    'bot_id': self.bot_id.id
                })
            
            _logger.info(f'کاربر {self.chat_id} به کمپین {campaign.name} پیوست')

            # شروع از اولین مرحله
            first_step = campaign.step_ids.sorted(lambda s: s.sequence)[:1]
            if first_step:
                participant.write({'current_step_id': first_step.id})
                # اجرای مرحله اول
                return participant.process_step(first_step)

            return True
            
        except Exception as e:
            _logger.error(f'خطا در پردازش پارامتر شروع {start_parameter}: {str(e)}')
            return False
