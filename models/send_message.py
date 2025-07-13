from odoo import models, fields, api
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)

class TelegramSendMessage(models.Model):
    _name = 'telegram.send.message'
    _description = 'ارسال پیام تلگرام'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc'

    bot_id = fields.Many2one('telegram.bot', string='ربات', required=True)
    chat_id = fields.Char(string='شناسه چت', required=True)
    message = fields.Text(string='متن پیام', required=True)
    sent_at = fields.Datetime(string='زمان ارسال')
    status = fields.Selection([
        ('draft', 'پیش‌نویس'),
        ('sending', 'در حال ارسال'),
        ('success', 'موفق'),
        ('failed', 'ناموفق')
    ], string='وضعیت', default='draft', tracking=True)
    error_message = fields.Text(string='پیام خطا')
    retry_count = fields.Integer(string='تعداد تلاش‌ها', default=0)
    
    @api.model_create_multi
    def create(self, vals_list):
        """ایجاد رکورد جدید"""
        for vals in vals_list:
            if vals.get('message') and len(vals['message']) > 4096:
                raise UserError('طول پیام نمی‌تواند بیشتر از 4096 کاراکتر باشد')
        return super().create(vals_list)

    def action_send_message(self):
        self.ensure_one()
        self._validate_message()
        
        try:
            self.write({'status': 'sending'})
            service = self.env['telegram.service'].new()
            response = service.send_message(
                chat_id=self.chat_id,
                message=self.message
            )
            
            self._handle_success()
            return self._get_success_notification()
            
        except Exception as e:
            return self._handle_error(str(e))

    def _validate_message(self):
        """اعتبارسنجی پیام قبل از ارسال"""
        if not self.chat_id:
            raise UserError('Chat ID الزامی است')
        if not self.message:
            raise UserError('پیام الزامی است')
        if not self.bot_id or not self.bot_id.api_token:
            raise UserError('توکن API تنظیم نشده است')

    def _handle_success(self):
        """پردازش ارسال موفق"""
        self.write({
            'sent_at': fields.Datetime.now(),
            'status': 'success',
            'error_message': False
        })

    def _handle_error(self, error_msg):
        """پردازش خطای ارسال"""
        self.write({
            'status': 'failed',
            'error_message': error_msg,
            'retry_count': self.retry_count + 1
        })
        return self._get_error_notification(error_msg)

    def _get_success_notification(self):
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'پیام',
                'message': 'پیام با موفقیت ارسال شد.',
                'type': 'success',
                'sticky': False,
            }
        }

    def _get_error_notification(self, error_msg):
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'خطا',
                'message': f'ارسال پیام ناموفق بود: {error_msg}',
                'type': 'danger',
                'sticky': False,
            }
        }

    @api.model
    def _send_pending_messages(self):
        """ارسال پیام‌های در صف انتظار"""
        messages = self.search([
            ('status', '=', 'draft'),
            ('message', '!=', False),
            ('chat_id', '!=', False),
            ('bot_id', '!=', False)
        ])
        for message in messages:
            try:
                message.action_send_message()
            except Exception as e:
                _logger.error(f"خطا در ارسال پیام {message.id}: {str(e)}")
                continue
