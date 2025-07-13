from odoo import models, fields, api

class TelegramPayment(models.Model):
    _name = 'telegram.payment'
    _description = 'پرداخت تلگرام'
    _order = 'create_date desc'

    name = fields.Char(string='شناسه پرداخت', required=True, copy=False, readonly=True, index=True, default='/')
    
    partner_id = fields.Many2one('res.partner', string='مخاطب', required=True, ondelete='cascade')
    telegram_info_id = fields.Many2one('telegram.info', string='اطلاعات تلگرام', ondelete='cascade')
    step_id = fields.Many2one('telegram.step', string='مرحله', ondelete='set null')
    
    amount = fields.Float(string='مبلغ', required=True)
    currency = fields.Selection([
        ('TON', 'TON'),
        ('XTR', 'Telegram Stars')
    ], string='واحد پول', required=True)
    
    telegram_charge_id = fields.Char(string='شناسه شارژ تلگرام', readonly=True)
    provider_charge_id = fields.Char(string='شناسه شارژ ارائه‌دهنده', readonly=True)
    
    state = fields.Selection([
        ('draft', 'پیش‌نویس'),
        ('paid', 'پرداخت شده'),
        ('failed', 'ناموفق')
    ], string='وضعیت', default='draft', required=True)
    
    error_message = fields.Text(string='پیام خطا', readonly=True)
    message_id = fields.Char(string='شناسه پیام', readonly=True)

    @api.model
    def create(self, vals):
        if vals.get('name', '/') == '/':
            vals['name'] = self.env['ir.sequence'].next_by_code('telegram.payment') or '/'
        return super(TelegramPayment, self).create(vals)
