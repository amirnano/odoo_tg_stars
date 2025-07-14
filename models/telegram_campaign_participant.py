from odoo import models, fields, api
import logging
from datetime import timedelta

_logger = logging.getLogger(__name__)

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
