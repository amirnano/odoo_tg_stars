from odoo import models, fields, api

class TelegramInfo(models.Model):
    _name = 'telegram.info'
    _description = 'اطلاعات تلگرام'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    partner_id = fields.Many2one('res.partner', string='شریک تجاری', required=True, ondelete='cascade')
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
