import logging
import re
from odoo import models, fields, api
from odoo.exceptions import UserError, ValidationError
from cryptography.fernet import Fernet

_logger = logging.getLogger(__name__)

class TelegramBot(models.Model):
    _name = 'telegram.bot'
    _description = 'ربات تلگرام'
    _sql_constraints = [
        ('unique_username', 'unique(username)', 'نام کاربری ربات باید یکتا باشد')
    ]

    name = fields.Char(string='نام ربات', required=True)
    api_token = fields.Char(string='توکن API', required=True, copy=False)
    username = fields.Char(string='نام کاربری ربات', required=True)
    payment_provider_token = fields.Char(string='توکن ارائه‌دهنده پرداخت')
    webhook_url = fields.Char(string='آدرس Webhook', compute='_compute_webhook_url', store=True)
    is_active = fields.Boolean(string='فعال', default=True)
    description = fields.Text(string='توضیحات')
    created_date = fields.Datetime(string='تاریخ ایجاد', default=fields.Datetime.now, readonly=True)
    last_sync = fields.Datetime(string='آخرین همگام‌سازی')

    def _encrypt_token(self, token):
        key = self.env['ir.config_parameter'].sudo().get_param('telegram.encryption_key')
        if not key:
            key = Fernet.generate_key()
            self.env['ir.config_parameter'].sudo().set_param('telegram.encryption_key', key)
        f = Fernet(key)
        return f.encrypt(token.encode()).decode()

    def _decrypt_token(self, encrypted_token):
        key = self.env['ir.config_parameter'].sudo().get_param('telegram.encryption_key')
        f = Fernet(key)
        return f.decrypt(encrypted_token.encode()).decode()

    @api.model_create_multi
    def create(self, vals_list):
        """ایجاد رکورد جدید"""
        for vals in vals_list:
            if vals.get('api_token'):
                vals['api_token'] = self._encrypt_token(vals['api_token'])
        return super().create(vals_list)

    def write(self, vals):
        if vals.get('api_token'):
            vals['api_token'] = self._encrypt_token(vals['api_token'])
        return super().write(vals)

    @api.constrains('api_token')
    def _check_api_token(self):
        for record in self:
            decrypted_token = self._decrypt_token(record.api_token)
            if not re.match(r'^\d+:[\w-]+$', decrypted_token):
                raise ValidationError('فرمت توکن API نامعتبر است')
            
    @api.depends('api_token')
    def _compute_webhook_url(self):
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        for record in self:
            record.webhook_url = f"{base_url}/telegram/webhook/{record.id}"

    def action_set_webhook(self):
        """تنظیم webhook"""
        self.ensure_one()
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        
        # تبدیل http به https
        if base_url.startswith('http://'):
            base_url = base_url.replace('http://', 'https://')
        elif not base_url.startswith('https://'):
            base_url = f'https://{base_url}'
        
        webhook_url = f"{base_url}/telegram/webhook/{self.id}"
        
        service = self.env['telegram.service'].with_context(bot_id=self.id).new()
        try:
            # اول webhook قبلی را حذف می‌کنیم
            service.delete_webhook()
            # سپس webhook جدید را تنظیم می‌کنیم
            service.set_webhook(webhook_url)
            
            self.write({
                'webhook_url': webhook_url,
                'last_sync': fields.Datetime.now()
            })
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'موفق',
                    'message': 'Webhook با موفقیت تنظیم شد',
                    'type': 'success',
                }
            }
        except Exception as e:
            raise UserError(f"خطا در تنظیم webhook: {str(e)}")
 