from odoo import models, fields, api
from odoo.tools.safe_eval import safe_eval
from odoo.exceptions import ValidationError, UserError
from bs4 import BeautifulSoup
import logging
from time import sleep
import random
import re

_logger = logging.getLogger(__name__)

class TelegramSendMessageWizard(models.TransientModel):
    _name = 'telegram.send.message.wizard'
    _description = 'ویزارد ارسال پیام تلگرام'

    # فیلدهای اصلی
    message = fields.Html(string='متن پیام', required=True)
    attachment = fields.Binary(string='فایل پیوست')
    attachment_name = fields.Char(string='نام فایل')
    attachment_type = fields.Selection([
        ('photo', 'تصویر'),
        ('video', 'ویدئو'),
        ('audio', 'صوت'),
        ('document', 'سند')
    ], string='نوع فایل', compute='_compute_attachment_type', store=True)
    use_html_format = fields.Boolean(string='استفاده از فرمت HTML', default=True)
    bot_id = fields.Many2one('telegram.bot', string='ربات', required=True,
                            domain=[('is_active', '=', True)])

    # فیلتر مخاطبین
    domain = fields.Char(string='دامنه فیلتر')
    participant_count = fields.Integer(string='تعداد مخاطبین', compute='_compute_participant_count')

    # Add new fields
    is_scheduled = fields.Boolean(string='زمانبندی شده', default=False)
    scheduled_date = fields.Datetime(string='زمان ارسال')

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
        preview = preview.replace('<del>', '').replace('</del>', 'судар')
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

    @api.depends('domain')
    def _compute_participant_count(self):
        for wizard in self:
            domain = []
            if isinstance(wizard.domain, list):  # اگر domain لیست باشد
                domain.extend(wizard.domain)
            elif wizard.domain:  # اگر domain رشته باشد
                try:
                    ctx = dict(wizard._context or {})
                    domain.extend(safe_eval(wizard.domain, ctx))
                except Exception as e:
                    _logger.error(f"Error evaluating domain: {str(e)}")
                    domain = []
            domain.append(('telegram_ids', '!=', False))
            wizard.participant_count = wizard.env['res.partner'].search_count(domain)

    def show_batch_report(self, stats, is_final=False):
        """نمایش گزارش هر دسته"""
        batch_message = f"""گزارش ارسال پیام {'' if is_final else f'(دسته {stats["batch_number"]} از {stats["total_batches"]})'}:
• تعداد کل: {stats['total']} نفر
• موفق تا این لحظه: {stats['success']} نفر
• بلاک شده: {stats['blocked']} نفر
• غیرفعال: {stats['deactivated']} نفر
• خطای دیگر: {stats['error']} نفر
{'برای مشاهده جزئیات خطاها به بخش لاگ‌ها مراجعه کنید.' if is_final else ''}"""

        self.env['bus.bus']._sendone(
            self.env.user.partner_id, 
            'telegram_message_progress', 
            {
                'message': batch_message,
                'type': 'info' if not is_final else 'success',
                'title': 'پایان ارسال پیام' if is_final else f'گزارش دسته {stats["batch_number"]}',
                'sticky': is_final
            }
        )

        # ثبت لاگ برای هر دسته
        if stats['failed_partners']:
            log_message = f"گزارش خطاهای ارسال پیام - دسته {stats['batch_number']}:\n\n"
            for failed in stats['failed_partners']:
                log_message += f"🔴 {failed['partner']}:\n"
                for error in failed['errors']:
                    log_message += f"  - {error}\n"
            
            self.env['telegram.log'].create({
                'name': f'خطا در ارسال گروهی پیام - دسته {stats["batch_number"]}',
                'description': log_message,
                'type': 'error',
                'bot_id': self.bot_id.id,
                'direction': 'outgoing'
            })

    def action_send_message(self):
        """ارسال پیام به مخاطبان"""
        self.ensure_one()

        # تبدیل HTML به متن ساده
        message = self.message
        if self.use_html_format:
            message = re.sub(r'<p[^>]*>', '', message)
            message = message.replace('</p>', '')
            allowed_tags = ['b', 'strong', 'i', 'em', 'u', 's', 'a', 'code', 'pre']
            for tag in allowed_tags:
                message = message.replace(f'<{tag}>', f'<{tag}>')
                message = message.replace(f'</{tag}>', f'</{tag}>')
            message = re.sub(r'<[^>]+>', '', message)

        # یافتن مخاطبان
        domain = []
        if isinstance(self.domain, list):
            domain.extend(self.domain)
        elif self.domain:
            try:
                ctx = dict(self._context or {})
                domain.extend(safe_eval(self.domain, ctx))
            except Exception as e:
                _logger.error(f"Error evaluating domain: {str(e)}")
                domain = []
        domain.append(('telegram_ids', '!=', False))
        
        partners = self.env['res.partner'].search(domain)
        if not partners:
            raise ValidationError('هیچ مخاطبی برای ارسال پیام یافت نشد')

        # ایجاد شناسه یکتا برای این دسته ارسال
        batch_id = f'bulk_{fields.Datetime.now().strftime("%Y%m%d%H%M%S")}'

        # تنظیمات ارسال
        batch_size = 20  # تعداد پیام در هر دسته
        delay_between_batches = 65  # تاخیر بین دسته‌ها (ثانیه)

        # آمار ارسال
        stats = {
            'total': len(partners),
            'success': 0,
            'blocked': 0,
            'deactivated': 0,
            'error': 0,
            'failed_partners': [],
            'batch_number': 0,
            'total_batches': (len(partners) + batch_size - 1) // batch_size
        }

        for i in range(0, len(partners), batch_size):
            batch = partners[i:i + batch_size]
            stats['batch_number'] += 1
            batch_failed_partners = []
            
            for partner in batch:
                # بررسی ارسال قبلی
                previous_send = self.env['telegram.message.history'].search([
                    ('partner_id', '=', partner.id),
                    ('batch_id', '=', batch_id),
                    ('state', '=', 'sent')
                ], limit=1)
                
                if previous_send:
                    _logger.info(f"پیام قبلاً به {partner.name} ارسال شده است")
                    continue

                for telegram_info in partner.telegram_ids:
                    try:
                        service = self.env['telegram.service'].sudo().with_context(
                            bot_id=telegram_info.bot_id.id
                        ).new()
                        
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
                        
                        # ثبت ارسال موفق
                        self.env['telegram.message.history'].create({
                            'partner_id': partner.id,
                            'message': message,
                            'attachment_name': self.attachment_name if self.attachment else False,
                            'state': 'sent',
                            'batch_id': batch_id,
                            'bot_id': telegram_info.bot_id.id,
                            'chat_id': telegram_info.chat_id
                        })
                        
                        stats['success'] += 1
                        break
                        
                    except Exception as e:
                        error_msg = str(e)
                        state = 'blocked' if 'bot was blocked' in error_msg else \
                               'deactivated' if 'user is deactivated' in error_msg else 'failed'
                        
                        # ثبت خطا در تاریخچه
                        self.env['telegram.message.history'].create({
                            'partner_id': partner.id,
                            'message': message,
                            'attachment_name': self.attachment_name if self.attachment else False,
                            'state': state,
                            'error_message': error_msg,
                            'batch_id': batch_id,
                            'bot_id': telegram_info.bot_id.id,
                            'chat_id': telegram_info.chat_id
                        })
                        
                        if state == 'blocked':
                            stats['blocked'] += 1
                        elif state == 'deactivated':
                            stats['deactivated'] += 1
                        else:
                            stats['error'] += 1
                        
                        batch_failed_partners.append({
                            'partner': partner.name,
                            'errors': [error_msg]
                        })
                        _logger.error(f"Error sending message to {partner.name} ({telegram_info.chat_id}): {error_msg}")
                        continue

                # اضافه کردن خطاهای این دسته به لیست کلی
                stats['failed_partners'].extend(batch_failed_partners)
                
                # نمایش گزارش این دسته
                self.show_batch_report(stats)
                
            # تاخیر بین دسته‌ها
            if i + batch_size < len(partners):
                sleep(delay_between_batches)

        # نمایش گزارش نهایی
        self.show_batch_report(stats, is_final=True)
        
        return {
            'type': 'ir.actions.client',
            'tag': 'reload',
        }

    def action_schedule_message(self):
        """زمانبندی پیام برای ارسال"""
        self.ensure_one()
        
        if not self.scheduled_date:
            raise ValidationError('لطفا زمان ارسال را مشخص کنید')
        
        scheduled_msg = self.env['telegram.scheduled.message'].create({
            'name': 'پیام زمانبندی شده',
            'message': self.message,
            'attachment': self.attachment,
            'attachment_name': self.attachment_name,
            'use_html_format': self.use_html_format,
            'bot_id': self.bot_id.id,
            'domain': self.domain,
            'scheduled_date': self.scheduled_date,
            'state': 'scheduled'
        })
        
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'telegram.scheduled.message',
            'res_id': scheduled_msg.id,
            'view_mode': 'form',
            'target': 'current',
        }