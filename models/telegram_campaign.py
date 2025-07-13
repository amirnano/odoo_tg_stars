from odoo import models, fields, api
from odoo.exceptions import ValidationError

class TelegramCampaign(models.Model):
    _name = 'telegram.campaign'
    _description = 'کمپین تلگرام'
    _order = 'create_date desc'

    name = fields.Char(string='نام کمپین', required=True)
    message = fields.Text(string='متن پیام', required=True)
    attachment_name = fields.Char(string='نام فایل پیوست')
    
    message_count = fields.Integer(string='تعداد کل پیام‌ها', compute='_compute_stats')
    success_count = fields.Integer(string='ارسال موفق', compute='_compute_stats')
    blocked_count = fields.Integer(string='بلاک شده', compute='_compute_stats')
    failed_count = fields.Integer(string='خطا', compute='_compute_stats')
    
    bot_id = fields.Many2one('telegram.bot', string='ربات', required=True, 
                            domain=[('is_active', '=', True)],
                            ondelete='cascade')
    start_parameter = fields.Char(string='پارامتر شروع', required=True)
    start_message = fields.Text(string='پیام شروع')
    active = fields.Boolean(string='فعال', default=True)
    state = fields.Selection([
        ('draft', 'پیش‌نویس'),
        ('active', 'فعال'),
        ('done', 'پایان یافته')
    ], string='وضعیت', default='draft')
    
    step_ids = fields.One2many('telegram.step', 'campaign_id', string='مراحل')
    
    participant_ids = fields.One2many('telegram.campaign.participant', 'campaign_id', 
                                    string='شرکت‌کنندگان')
    
    message_history_ids = fields.One2many(
        'telegram.message.history',
        'campaign_id',
        string='تاریخچه پیام‌ها'
    )
    
    _sql_constraints = [
        ('unique_start_parameter', 
         'UNIQUE(start_parameter)',
         'پارامتر شروع باید یکتا باشد')
    ]

    @api.depends('message_history_ids')
    def _compute_stats(self):
        for record in self:
            history = self.env['telegram.message.history'].search([
                ('campaign_id', '=', record.id)
            ])
            record.message_count = len(history)
            record.success_count = len(history.filtered(lambda r: r.state == 'sent'))
            record.blocked_count = len(history.filtered(lambda r: r.state == 'blocked'))
            record.failed_count = len(history.filtered(lambda r: r.state in ['failed', 'deactivated']))

    def action_activate(self):
        """فعال‌سازی کمپین"""
        self.ensure_one()
        if not self.step_ids:
            raise ValidationError('کمپین باید حداقل یک مرحله داشته باشد')
        if not self.bot_id:
            raise ValidationError('ربات برای کمپین انتخاب نشده است')
        if not self.bot_id.is_active:
            raise ValidationError('ربات انتخاب شده غیرفعال است')
        
        self.write({
            'state': 'active',
            'active': True
        })

    def action_done(self):
        """پایان کمپین"""
        self.ensure_one()
        self.write({'state': 'done'})

    def copy(self, default=None):
        """تکثیر کمپین با پارامتر شروع یکتا و کپی تمام مراحل"""
        self.ensure_one()
        if default is None:
            default = {}
            
        # اضافه کردن پسوند به پارامتر شروع
        if 'start_parameter' not in default:
            # پیدا کردن کپی‌های موجود
            base_param = self.start_parameter
            existing_copies = self.search([
                ('start_parameter', 'like', f'{base_param}_%')
            ]).mapped('start_parameter')
            
            # پیدا کردن شماره بعدی
            counter = 1
            while f"{base_param}_{counter}" in existing_copies:
                counter += 1
                
            default['start_parameter'] = f"{base_param}_{counter}"
            
        # اضافه کردن پسوند به نام
        if 'name' not in default:
            default['name'] = f"{self.name} (کپی {counter})"
        
        # کپی کردن کمپین
        new_campaign = super().copy(default)
        
        # کپی کردن مراحل
        for step in self.step_ids:
            step.copy({
                'campaign_id': new_campaign.id,
                'sequence': step.sequence,
                'name': step.name,
                'message_type': step.message_type,
                'content': step.content,
                'target_model_id': step.target_model_id.id if step.target_model_id else False,
                'target_field_id': step.target_field_id.id if step.target_field_id else False,
                'condition': step.condition,
                'validation_type': step.validation_type,
                'min_length': step.min_length,
                'max_length': step.max_length,
                'regex_pattern': step.regex_pattern,
                'error_message': step.error_message,
            })
            
        return new_campaign

    def unlink(self):
        """حذف کمپین و مراحل مرتبط"""
        # حذف مراحل
        self.mapped('step_ids').unlink()
        return super().unlink()