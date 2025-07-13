from odoo import models, fields, api

class TelegramMessageHistory(models.Model):
    _name = 'telegram.message.history'
    _description = 'تاریخچه پیام‌های تلگرام'
    _order = 'create_date desc'

    partner_id = fields.Many2one('res.partner', string='مخاطب', ondelete='cascade') # required=True removed
    message = fields.Html(string='متن پیام')
    attachment_name = fields.Char(string='نام فایل')
    state = fields.Selection([
        ('sent', 'ارسال شده'),
        ('blocked', 'مسدود شده توسط کاربر'),
        ('deactivated', 'حساب غیرفعال'),
        ('failed', 'خطا در ارسال')
    ], string='وضعیت', required=True, default='failed', index=True) # Added index
    error_message = fields.Text(string='علت خطا')
    campaign_id = fields.Many2one('telegram.campaign', string='کمپین', ondelete='cascade', index=True) # Added index
    bot_id = fields.Many2one('telegram.bot', string='ربات', ondelete='set null') # Added ondelete
    chat_id = fields.Char(string='شناسه چت', index=True) # Added index
    
    # New field to link to the scheduled message
    scheduled_message_id = fields.Many2one(
        'telegram.scheduled.message', 
        string='Scheduled Message Ref', 
        ondelete='set null', 
        index=True,
        readonly=True 
    )

    # فیلدهای جدید برای بهبود گزارش‌گیری
    is_success = fields.Boolean(string='ارسال موفق', 
                              compute='_compute_is_success', 
                              store=True)
    attempt_count = fields.Integer(string='تعداد تلاش', default=1)
    
    @api.onchange('campaign_id')
    def _onchange_campaign_id(self):
        """وقتی کمپین انتخاب می‌شود، ربات آن را تنظیم کن"""
        if self.campaign_id and self.campaign_id.bot_id: # Check if campaign_id.bot_id exists
            self.bot_id = self.campaign_id.bot_id.id # Assign the ID

    @api.model_create_multi
    def create(self, vals_list):
        """اطمینان از تنظیم ربات و تلاش برای یافتن مخاطب برای هر رکورد"""
        for vals in vals_list:
            # Ensure bot_id is set, trying from campaign or scheduled message if not directly provided
            if not vals.get('bot_id'):
                if vals.get('campaign_id'):
                    campaign = self.env['telegram.campaign'].browse(vals['campaign_id'])
                    if campaign and campaign.bot_id:
                        vals['bot_id'] = campaign.bot_id.id
                elif vals.get('scheduled_message_id'):
                    scheduled_msg = self.env['telegram.scheduled.message'].browse(vals['scheduled_message_id'])
                    if scheduled_msg and scheduled_msg.bot_id:
                         vals['bot_id'] = scheduled_msg.bot_id.id
            
            # Attempt to link partner_id if not set and chat_id is available
            if not vals.get('partner_id') and vals.get('chat_id'):
                partner_info_domain = [('chat_id', '=', vals['chat_id'])]
                if vals.get('bot_id'): # Be more specific if bot_id is known
                    partner_info_domain.append(('bot_id', '=', vals['bot_id']))

                partner_info = self.env['telegram.info'].search(partner_info_domain, limit=1)
                if partner_info and partner_info.partner_id:
                    vals['partner_id'] = partner_info.partner_id.id
        return super().create(vals_list)

    @api.depends('state')
    def _compute_is_success(self):
        for record in self:
            record.is_success = record.state == 'sent'

    def name_get(self):
        state_selection_dict = dict(self._fields['state'].selection)
        res = []
        for rec in self:
            partner_name = rec.partner_id.name if rec.partner_id else (rec.chat_id or 'Unlinked Chat')
            state_display = state_selection_dict.get(rec.state, rec.state) # Handle if state is somehow not in selection
            res.append((rec.id, f"{partner_name} - {state_display}"))
        return res