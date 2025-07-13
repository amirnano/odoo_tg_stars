from odoo import models, fields, api
from odoo.exceptions import UserError

class ResPartner(models.Model):
    _inherit = 'res.partner'

    telegram_ids = fields.One2many('telegram.info', 'partner_id', string='اطلاعات تلگرام')
    telegram_count = fields.Integer(string='تعداد تلگرام', compute='_compute_telegram_count')
    campaign_participant_ids = fields.One2many(
        'telegram.campaign.participant', 
        'partner_id',
        string='کمپین‌های تلگرام'
    )

    @api.depends('telegram_ids')
    def _compute_telegram_count(self):
        for partner in self:
            partner.telegram_count = len(partner.telegram_ids)

    def action_view_telegram_info(self):
        self.ensure_one()
        return {
            'name': 'اطلاعات تلگرام',
            'type': 'ir.actions.act_window',
            'res_model': 'telegram.info',
            'view_mode': 'tree,form',
            'domain': [('partner_id', '=', self.id)],
            'context': {'default_partner_id': self.id},
        }

    def action_open_send_message_wizard(self):
        self.ensure_one()
        if not self.telegram_ids:
            raise UserError('این شریک تجاری به هیچ رباتی متصل نیست.')
            
        return {
            'name': 'ارسال پیام تلگرام',
            'type': 'ir.actions.act_window',
            'res_model': 'telegram.send.message.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_partner_id': self.id,
                'default_bot_id': self.telegram_ids[0].bot_id.id
            }
        }

    def unlink(self):
        """حذف مخاطب و اطلاعات تلگرام مرتبط"""
        # حذف اطلاعات تلگرام مرتبط
        telegram_infos = self.env['telegram.info'].search([
            ('partner_id', 'in', self.ids)
        ])
        if telegram_infos:
            telegram_infos.unlink()
            
        return super().unlink()
