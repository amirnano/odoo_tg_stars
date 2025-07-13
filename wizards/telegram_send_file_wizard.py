from odoo import models, fields, api
from odoo.exceptions import UserError
import base64

class TelegramSendFileWizard(models.TransientModel):
    _name = 'telegram.send.file.wizard'
    _description = 'ویزارد ارسال فایل تلگرام'

    bot_id = fields.Many2one('telegram.bot', string='ربات', required=True)
    partner_id = fields.Many2one('res.partner', string='مخاطب')
    chat_id = fields.Char(string='شناسه چت')
    file_type = fields.Selection([
        ('photo', 'عکس'),
        ('document', 'فایل'),
        ('video', 'ویدیو'),
        ('audio', 'فایل صوتی')
    ], string='نوع فایل', required=True, default='photo')
    file = fields.Binary(string='فایل', required=True)
    filename = fields.Char(string='نام فایل')
    caption = fields.Text(string='توضیحات')

    @api.onchange('partner_id')
    def _onchange_partner_id(self):
        """دریافت chat_id از اطلاعات تلگرام مخاطب"""
        if self.partner_id and self.bot_id:
            telegram_info = self.env['telegram.info'].search([
                ('partner_id', '=', self.partner_id.id),
                ('bot_id', '=', self.bot_id.id)
            ], limit=1)
            if telegram_info:
                self.chat_id = telegram_info.chat_id
            else:
                self.chat_id = False

    def action_send_file(self):
        """ارسال فایل به تلگرام"""
        self.ensure_one()
        
        if not self.chat_id:
            raise UserError('شناسه چت الزامی است')
            
        if not self.file:
            raise UserError('فایل الزامی است')

        try:
            # تبدیل فایل به باینری
            file_content = base64.b64decode(self.file)
            service = self.env['telegram.service'].with_context(bot_id=self.bot_id.id).new()
            
            # ارسال فایل بر اساس نوع
            if self.file_type == 'photo':
                response = service.send_photo(
                    chat_id=self.chat_id,
                    photo=file_content,
                    caption=self.caption
                )
            elif self.file_type == 'document':
                response = service.send_document(
                    chat_id=self.chat_id,
                    document=file_content,
                    filename=self.filename,
                    caption=self.caption
                )
            elif self.file_type == 'video':
                response = service.send_video(
                    chat_id=self.chat_id,
                    video=file_content,
                    caption=self.caption
                )
            elif self.file_type == 'audio':
                response = service.send_audio(
                    chat_id=self.chat_id,
                    audio=file_content,
                    caption=self.caption
                )
                
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'موفق',
                    'message': 'فایل با موفقیت ارسال شد',
                    'type': 'success',
                }
            }
            
        except Exception as e:
            raise UserError(f"خطا در ارسال فایل: {str(e)}") 