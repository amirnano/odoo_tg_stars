from odoo import models, fields, api
from odoo.exceptions import UserError

class TelegramEditor(models.Model):
    _name = 'telegram.editor'
    _description = 'ویرایشگر پیام تلگرام'

    name = fields.Char(string='عنوان', required=True)
    content = fields.Html(string='محتوا')
    preview = fields.Text(string='پیش‌نمایش HTML', compute='_compute_preview')
    attachment_ids = fields.Many2many('ir.attachment', string='فایل‌های پیوست')
    
    @api.depends('content')
    def _compute_preview(self):
        """تبدیل محتوای HTML به فرمت تلگرام"""
        for record in self:
            if record.content:
                # تبدیل تگ‌های HTML به فرمت تلگرام
                preview = record.content
                preview = preview.replace('<strong>', '<b>').replace('</strong>', '</b>')
                preview = preview.replace('<em>', '<i>').replace('</em>', '</i>')
                preview = preview.replace('<del>', '<s>').replace('</del>', '</s>')
                preview = preview.replace('<code>', '<pre>').replace('</code>', '</pre>')
                record.preview = preview
            else:
                record.preview = ''

    def send_message(self, chat_id):
        """ارسال پیام با استفاده از ویرایشگر"""
        self.ensure_one()
        
        if not self.content:
            raise UserError('محتوای پیام خالی است')
            
        service = self.env['telegram.service'].sudo().with_context(bot_id=self.env.context.get('bot_id')).new()
        
        # ارسال فایل‌های پیوست
        files = []
        for attachment in self.attachment_ids:
            files.append({
                'type': 'photo' if attachment.mimetype.startswith('image') else 'document',
                'content': attachment.datas,
                'caption': attachment.name
            })
            
        # ارسال پیام
        return service.send_message(
            chat_id=chat_id,
            message=self.preview,
            parse_mode='HTML',
            files=files
        )

    def action_send_message(self):
        """متد wrapper برای فراخوانی از دکمه"""
        self.ensure_one()
        return self.send_message(self.chat_id)

    @api.model_create_multi
    def create(self, vals_list):
        """ایجاد رکورد جدید"""
        return super().create(vals_list) 