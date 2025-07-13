from odoo import models, fields

class TelegramSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    telegram_api_token = fields.Char(
        string="Telegram API Token",
        config_parameter='partner_telegram.telegram_api_token'
    )
