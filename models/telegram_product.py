from odoo import models, fields

class TelegramProduct(models.Model):
    _name = 'telegram.product'
    _description = 'محصول تلگرام'

    name = fields.Char(string='نام محصول', required=True)
    price = fields.Float(string='قیمت', required=True)
    currency = fields.Selection([
        ('TON', 'TON'),
        ('XTR', 'Telegram Stars')
    ], string='واحد پول', required=True, default='TON')
    
    product_type = fields.Selection([
        ('file', 'فایل'),
        ('subscription', 'اشتراک')
    ], string='نوع محصول', required=True, default='file')
    
    attachment = fields.Binary(string='فایل ضمیمه')
    attachment_name = fields.Char(string='نام فایل ضمیمه')
    
    description = fields.Text(string='توضیحات')
    is_active = fields.Boolean(string='فعال', default=True)
