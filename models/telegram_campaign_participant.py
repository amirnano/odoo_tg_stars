from odoo import models, fields, api

class TelegramCampaignParticipant(models.Model):
    _name = 'telegram.campaign.participant'
    _description = 'شرکت‌کنندگان کمپین'
    _order = 'join_date desc'  # مرتب‌سازی بر اساس تاریخ پیوستن

    campaign_id = fields.Many2one('telegram.campaign', string='کمپین', required=True, ondelete='cascade')
    telegram_info_id = fields.Many2one('telegram.info', string='اطلاعات تلگرام', required=True, ondelete='cascade')
    partner_id = fields.Many2one(related='telegram_info_id.partner_id', store=True, string='شریک تجاری')
    join_date = fields.Datetime(string='تاریخ پیوستن', required=True)
    
    # فیلدهای مرتبط برای نمایش در لیست
    telegram_id = fields.Char(related='telegram_info_id.telegram_id', string='شناسه تلگرام', store=True)
    telegram_username = fields.Char(related='telegram_info_id.telegram_username', string='نام کاربری تلگرام', store=True)
    chat_id = fields.Char(related='telegram_info_id.chat_id', string='شناسه چت', store=True)
    bot_id = fields.Many2one(related='telegram_info_id.bot_id', string='ربات', store=True)
    current_step_id = fields.Many2one('telegram.step', string='مرحله فعلی', ondelete='set null')
    
    # اضافه کردن فیلد active برای جلوگیری از حذف رکوردها
    active = fields.Boolean(default=True, string='فعال')

    _sql_constraints = [
        ('unique_participant', 
         'UNIQUE(campaign_id, telegram_info_id, join_date)',
         'این کاربر قبلاً در این کمپین ثبت شده است!')
    ]

    @api.model
    def create(self, vals):
        """اطمینان از ثبت تاریخ صحیح پیوستن"""
        if not vals.get('join_date'):
            vals['join_date'] = fields.Datetime.now()
        return super().create(vals) 