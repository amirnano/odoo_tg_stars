from odoo import models, fields, api

class TelegramLog(models.Model):
    _name = 'telegram.log'
    _description = 'لاگ تلگرام'
    _order = 'create_date desc'

    name = fields.Char(string='عنوان', required=True)
    description = fields.Text(string='توضیحات')
    type = fields.Selection([
        ('info', 'اطلاعات'),
        ('warning', 'هشدار'),
        ('error', 'خطا')
    ], string='نوع', required=True, default='info')
    batch_number = fields.Integer(string='شماره دسته')
    bot_id = fields.Many2one('telegram.bot', string='ربات', required=True, ondelete='cascade')
    direction = fields.Selection([
        ('incoming', 'ورودی'),
        ('outgoing', 'خروجی')
    ], string='جهت', required=True)
    request_data = fields.Text(string='داده درخواست')
    response_data = fields.Text(string='داده پاسخ')
    status_code = fields.Integer(string='کد وضعیت')
    error_message = fields.Text(string='پیام خطا')
    create_date = fields.Datetime(string='تاریخ ایجاد', readonly=True)

    _sql_constraints = [
        ('check_direction', 
         "CHECK(direction IN ('incoming', 'outgoing'))",
         'جهت باید incoming یا outgoing باشد')
    ]

    @api.model
    def log_error(self, name, description, bot_id=None):
        """ثبت خطا با تنظیم خودکار bot_id"""
        if not bot_id and self.env.context.get('default_bot_id'):
            bot_id = self.env.context.get('default_bot_id')
        
        vals = {
            'name': name,
            'description': description,
            'type': 'error',
            'bot_id': bot_id or self.env['telegram.bot'].search([], limit=1).id,
            'direction': 'outgoing'
        }
        return self.create(vals)