from odoo.tests import common, tagged
from odoo import fields
from unittest.mock import patch, MagicMock

@tagged('post_install', '-at_install')
class TestTelegramIntegration(common.TransactionCase):

    def setUp(self):
        super().setUp()
        self.bot = self.env['telegram.bot'].create({
            'name': 'Test Bot',
            'api_token': '123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11',
            'username': 'test_bot_user'
        })
        self.partner = self.env['res.partner'].create({'name': 'Test Partner'})
        self.telegram_info = self.env['telegram.info'].create({
            'partner_id': self.partner.id,
            'bot_id': self.bot.id,
            'telegram_id': '1234567890',
            'chat_id': '987654321',
            'telegram_username': 'testpartneruser'
        })
        self.campaign = self.env['telegram.campaign'].create({
            'name': 'Test Campaign',
            'bot_id': self.bot.id,
            'message': 'Test Message',
            'start_parameter': 'start_test'
        })
        self.step = self.env['telegram.step'].create({
            'name': 'Test Step',
            'campaign_id': self.campaign.id,
            'message_type': 'text',
            'content': 'Hello World'
        })

    def test_token_encryption(self):
        """تست رمزگذاری و رمزگشایی توکن"""
        original_token = '123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11'
        encrypted_token = self.bot._encrypt_token(original_token)
        self.assertNotEqual(original_token, encrypted_token)
        decrypted_token = self.bot._decrypt_token(encrypted_token)
        self.assertEqual(original_token, decrypted_token)

    def test_input_validation(self):
        """تست اعتبارسنجی ورودی"""
        step = self.env['telegram.step'].create({
            'name': 'Validation Step',
            'campaign_id': self.campaign.id,
            'validation_type': 'email'
        })
        is_valid, msg = step.validate_input('test@example.com')
        self.assertTrue(is_valid)
        is_valid, msg = step.validate_input('invalid-email')
        self.assertFalse(is_valid)
        self.assertEqual(msg, 'لطفاً یک ایمیل معتبر وارد کنید')

    @patch('odoo.addons.telegram.services.telegram_service.TelegramService._send_request')
    def test_process_step(self, mock_send_request):
        """تست پردازش مراحل کمپین"""
        mock_send_request.return_value = {'ok': True, 'result': {'message_id': 123}}
        service = self.env['telegram.service'].with_context(bot_id=self.bot.id)
        result = service.process_step(self.step, self.telegram_info)
        self.assertTrue(result)
        mock_send_request.assert_called_once()

    def test_campaign_copy(self):
        """تست کپی کردن کمپین"""
        self.env['telegram.step'].create({
            'name': 'Step 2',
            'campaign_id': self.campaign.id,
            'message_type': 'text',
            'content': 'Step 2'
        })
        new_campaign = self.campaign.copy()
        self.assertEqual(new_campaign.name, f"{self.campaign.name} (کپی 1)")
        self.assertEqual(len(new_campaign.step_ids), 2)
        self.assertEqual(new_campaign.step_ids[0].name, self.step.name)

    @patch('odoo.addons.telegram.services.telegram_service.requests.post')
    def test_send_message_service(self, mock_post):
        """تست سرویس ارسال پیام"""
        mock_response = MagicMock()
        mock_response.json.return_value = {'ok': True, 'result': {'message_id': 123}}
        mock_post.return_value = mock_response

        service = self.env['telegram.service'].with_context(bot_id=self.bot.id)
        result = service.send_message(self.telegram_info.chat_id, 'Test')
        self.assertIsNotNone(result)
        self.assertEqual(result['message_id'], 123)