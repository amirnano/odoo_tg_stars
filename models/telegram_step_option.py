from odoo import models, fields, api

class TelegramStepOption(models.Model):
    _name = 'telegram.step.option'
    _description = 'گزینه‌های مرحله'
    _order = 'sequence'
    
    sequence = fields.Integer(string='ترتیب', default=10)
    step_id = fields.Many2one('telegram.step', string='مرحله', required=True, ondelete='cascade')
    text = fields.Char(string='متن', required=True)
    value = fields.Char(string='مقدار')
    next_step_id = fields.Many2one('telegram.step', string='مرحله بعدی')
    campaign_id = fields.Many2one(related='step_id.campaign_id', store=True)
    show_confirmation = fields.Boolean(string='نمایش پیام تأیید', default=False)
    confirmation_message = fields.Text(string='پیام تأیید')