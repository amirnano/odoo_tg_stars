from odoo import models, fields

class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    telegram_api_token = fields.Char(string='توکن API تلگرام')
    telegram_timeout = fields.Integer(string='مهلت زمانی (ثانیه)', default=10)
    telegram_max_retries = fields.Integer(string='حداکثر تلاش مجدد', default=3)
    telegram_api_url = fields.Char(
        string='آدرس API',
        default='https://api.telegram.org'
    )

    def get_values(self):
        res = super().get_values()
        params = self.env['ir.config_parameter'].sudo()
        res.update(
            telegram_api_token=params.get_param('telegram.api_token', default=''),
            telegram_timeout=int(params.get_param('telegram.timeout', '10')),
            telegram_max_retries=int(params.get_param('telegram.max_retries', '3')),
            telegram_api_url=params.get_param('telegram.api_url', 'https://api.telegram.org')
        )
        return res

    def set_values(self):
        super().set_values()
        params = self.env['ir.config_parameter'].sudo()
        params.set_param('telegram.api_token', self.telegram_api_token)
        params.set_param('telegram.timeout', str(self.telegram_timeout))
        params.set_param('telegram.max_retries', str(self.telegram_max_retries))
        params.set_param('telegram.api_url', self.telegram_api_url)