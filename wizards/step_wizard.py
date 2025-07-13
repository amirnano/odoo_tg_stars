from odoo import models, fields, api

class StepWizard(models.TransientModel):
    _name = 'telegram.step.wizard'
    _description = 'ویزارد افزودن مرحله'

    campaign_id = fields.Many2one('telegram.campaign', string='کمپین', required=True)
    name = fields.Char(string='نام', required=True)
    sequence = fields.Integer(string='ترتیب', default=10)
    message_type = fields.Selection([
        ('text', 'پیام متنی'),
        ('save_info', 'ذخیره اطلاعات'),
        ('contact_request', 'درخواست مخاطب'),
        ('conditional_message', 'پیام شرطی')
    ], string='نوع پیام', required=True)
    content = fields.Text(string='محتوا', required=True)
    
    # فیلدهای فایل
    attachment = fields.Binary(string='فایل پیوست')
    attachment_name = fields.Char(string='نام فایل')
    attachment_type = fields.Selection([
        ('image', 'تصویر'),
        ('video', 'ویدئو'),
        ('audio', 'صوت'),
        ('document', 'فایل')
    ], string='نوع فایل', compute='_compute_attachment_type', store=True)
    
    target_model_id = fields.Many2one('ir.model', string='مدل هدف')
    target_field_id = fields.Many2one('ir.model.fields', string='فیلد هدف',
        domain="[('model_id', '=', target_model_id)]")
    condition = fields.Char(string='شرط')

    # فیلدهای اعتبارسنجی
    validation_type = fields.Selection([
        ('none', 'بدون اعتبارسنجی'),
        ('text', 'متن'),
        ('number', 'عدد'),
        ('email', 'ایمیل'),
        ('phone', 'تلفن'),
        ('contact', 'مخاطب تلگرام')
    ], string='نوع اعتبارسنجی', default='none', required=True)
    
    min_length = fields.Integer(string='حداقل طول', default=0)
    max_length = fields.Integer(string='حداکثر طول', default=0)
    regex_pattern = fields.Char(string='الگوی Regex')
    error_message = fields.Text(string='پیام خطا')

    @api.depends('attachment_name')
    def _compute_attachment_type(self):
        for record in self:
            if not record.attachment_name:
                record.attachment_type = False
                continue
                
            extension = record.attachment_name.lower().split('.')[-1]
            if extension in ['jpg', 'jpeg', 'png', 'gif']:
                record.attachment_type = 'image'
            elif extension in ['mp4', 'avi', 'mkv', '3gp']:
                record.attachment_type = 'video'
            elif extension in ['mp3', 'wav', 'ogg']:
                record.attachment_type = 'audio'
            else:
                record.attachment_type = 'document'

    @api.onchange('message_type')
    def _onchange_message_type(self):
        if self.message_type == 'contact_request':
            self.validation_type = 'contact'
            self.content = 'برای تکمیل ثبت‌نام، لطفاً شماره تماس خود را به اشتراک بگذارید.\n\n🔘 دکمه "اشتراک‌گذاری شماره تماس" را لمس کنید.'
        elif self.message_type == 'save_info':
            self.validation_type = 'text'
            self.min_length = 2
            self.max_length = 50
            self.error_message = 'لطفاً یک متن معتبر وارد کنید'

    @api.onchange('target_model_id')
    def _onchange_target_model(self):
        """به‌روزرسانی دامنه فیلدها وقتی مدل تغییر می‌کند"""
        self.target_field_id = False
        if self.target_model_id:
            return {
                'domain': {
                    'target_field_id': [('model_id', '=', self.target_model_id.id)]
                }
            }
        return {
            'domain': {
                'target_field_id': []
            }
        }

    def action_add_step(self):
        self.ensure_one()
        vals = {
            'campaign_id': self.campaign_id.id,
            'name': self.name,
            'sequence': self.sequence,
            'message_type': self.message_type,
            'content': self.content,
            'target_model_id': self.target_model_id.id if self.target_model_id else False,
            'target_field_id': self.target_field_id.id if self.target_field_id else False,
            'condition': self.condition,
            'validation_type': self.validation_type,
            'min_length': self.min_length,
            'max_length': self.max_length,
            'regex_pattern': self.regex_pattern,
            'error_message': self.error_message,
            'attachment': self.attachment,
            'attachment_name': self.attachment_name,
        }
        step = self.env['telegram.step'].create(vals)
        return {'type': 'ir.actions.act_window_close'}