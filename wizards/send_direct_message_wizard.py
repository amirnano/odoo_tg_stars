from odoo import models, fields, api
from odoo.exceptions import ValidationError, UserError
from bs4 import BeautifulSoup
import logging

_logger = logging.getLogger(__name__)

class TelegramSendDirectMessageWizard(models.TransientModel):
    _name = 'telegram.send.direct.message.wizard'
    _description = 'ویزارد ارسال پیام تکی تلگرام'

    partner_id = fields.Many2one('res.partner', string='مخاطب', required=True)
    message = fields.Text(string='متن پیام', required=True)
    attachment = fields.Binary(string='فایل پیوست')
    attachment_name = fields.Char(string='نام فایل')
    attachment_type = fields.Selection([
        ('photo', 'تصویر'),
        ('video', 'ویدئو'),
        ('audio', 'صوت'),
        ('document', 'سند')
    ], string='نوع فایل', compute='_compute_attachment_type', store=True)
    use_html_format = fields.Boolean(string='استفاده از فرمت HTML', default=True)

    @api.model
    def default_get(self, fields):
        res = super().default_get(fields)
        if self._context.get('active_model') == 'res.partner' and self._context.get('active_id'):
            res['partner_id'] = self._context.get('active_id')
        return res

    def action_send_message(self):
        """ارسال پیام به مخاطب"""
        self.ensure_one()
        
        try:
            if not self.partner_id.telegram_ids:
                raise ValidationError('این مخاطب به هیچ رباتی متصل نیست')

            # تبدیل HTML به فرمت تلگرام
            message = self._convert_html_to_telegram(self.message)

            # ارسال پیام به همه اکانت‌های تلگرام مخاطب
            success_count = 0
            for telegram_info in self.partner_id.telegram_ids:
                try:
                    service = self.env['telegram.service'].sudo().with_context(bot_id=telegram_info.bot_id.id).new()
                    if self.attachment:
                        service.send_file(
                            chat_id=telegram_info.chat_id,
                            step=self,
                            caption=message
                        )
                    else:
                        service.send_message(
                            chat_id=telegram_info.chat_id,
                            message=message,
                            parse_mode='HTML' if self.use_html_format else None
                        )
                    success_count += 1
                except Exception as e:
                    _logger.error(f"Error sending message to {telegram_info.chat_id}: {str(e)}")
                    continue

            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'موفق',
                    'message': f'پیام به {success_count} اکانت تلگرام ارسال شد',
                    'type': 'success',
                }
            }

        except Exception as e:
            raise UserError(f"خطا در ارسال پیام: {str(e)}")

    def _convert_html_to_telegram(self, html_content):
        """تبدیل HTML به فرمت تلگرام"""
        if not html_content or not self.use_html_format:
            return html_content

        # تبدیل تگ‌های HTML به فرمت تلگرام
        preview = html_content
        
        # تبدیل کاراکترهای خاص
        preview = preview.replace('&nbsp;', ' ')  # تبدیل non-breaking space به فاصله معمولی
        preview = preview.replace('&amp;', '&')   # تبدیل &amp; به &
        preview = preview.replace('&lt;', '<')    # تبدیل &lt; به <
        preview = preview.replace('&gt;', '>')    # تبدیل &gt; به >
        
        # تبدیل تگ‌های HTML
        preview = preview.replace('<strong>', '<b>').replace('</strong>', '</b>')
        preview = preview.replace('<em>', '<i>').replace('</em>', '</i>')
        preview = preview.replace('<del>', '<s>').replace('</del>', '</s>')
        preview = preview.replace('<code>', '<pre>').replace('</code>', '</pre>')
        
        # حذف استایل‌ها و تگ‌های اضافی
        preview = preview.replace(' style="margin-bottom: 0px;"', '')
        preview = preview.replace(' data-oe-version="1.0"', '')
        preview = preview.replace('<p>', '').replace('</p>', '\n')
        preview = preview.replace('<div>', '').replace('</div>', '\n')
        preview = preview.replace('<br>', '\n')
        preview = preview.replace('<br/>', '\n')
        
        # حذف خطوط خالی اضافی و فاصله‌های اضافی
        lines = []
        for line in preview.split('\n'):
            line = ' '.join(part for part in line.split(' ') if part)  # حذف فاصله‌های اضافی
            if line.strip():
                lines.append(line.strip())
        preview = '\n'.join(lines)
        
        return preview

    @api.depends('attachment_name')
    def _compute_attachment_type(self):
        """محاسبه نوع فایل پیوست"""
        for record in self:
            if record.attachment_name:
                ext = record.attachment_name.lower().split('.')[-1]
                if ext in ['jpg', 'jpeg', 'png', 'gif']:
                    record.attachment_type = 'photo'
                elif ext in ['mp4', 'avi', 'mkv']:
                    record.attachment_type = 'video'
                elif ext in ['mp3', 'wav', 'ogg']:
                    record.attachment_type = 'audio'
                else:
                    record.attachment_type = 'document'
            else:
                record.attachment_type = False 