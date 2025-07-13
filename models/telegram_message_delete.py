from odoo import models, fields, api
from datetime import datetime, timedelta
import logging

_logger = logging.getLogger(__name__)

class TelegramMessageDelete(models.Model):
    _name = 'telegram.message.delete'
    _description = 'پیام‌های ارسال شده تلگرام'
    _order = 'delete_time'

    chat_id = fields.Char(string='شناسه چت', required=True)
    message_id = fields.Integer(string='شناسه پیام', required=True)
    bot_id = fields.Many2one('telegram.bot', string='ربات', required=True)
    step_id = fields.Many2one('telegram.step', string='مرحله')
    delete_time = fields.Datetime(string='زمان حذف', required=True)
    state = fields.Selection([
        ('pending', 'در انتظار'),
        ('deleted', 'حذف شده'),
        ('failed', 'خطا در حذف')
    ], string='وضعیت', default='pending', required=True)
    error_message = fields.Text(string='پیام خطا')

    _sql_constraints = [
        ('unique_message', 'unique(chat_id,message_id,bot_id)', 
         'هر پیام فقط یک‌بار می‌تواند ثبت شود!')
    ]

    def _cron_delete_messages(self):
        """حذف پیام‌های منقضی شده"""
        _logger.info("شروع حذف پیام‌های منقضی شده")
        messages = self.search([
            ('state', '=', 'pending'),
            ('delete_time', '<=', fields.Datetime.now())
        ])
        
        for message in messages:
            try:
                _logger.info(f"حذف پیام {message.message_id} از چت {message.chat_id}")
                service = self.env['telegram.service'].sudo().with_context(
                    bot_id=message.bot_id.id
                ).new()
                
                result = service.delete_message(
                    chat_id=message.chat_id,
                    message_id=message.message_id
                )
                
                if result:
                    message.write({'state': 'deleted'})
                    _logger.info(f"پیام {message.message_id} با موفقیت حذف شد")
                else:
                    message.write({
                        'state': 'failed',
                        'error_message': 'خطا در حذف پیام از تلگرام'
                    })
                    _logger.error(f"خطا در حذف پیام {message.message_id}")
                    
            except Exception as e:
                message.write({
                    'state': 'failed',
                    'error_message': str(e)
                })
                _logger.error(f"خطا در حذف پیام {message.message_id}: {str(e)}")