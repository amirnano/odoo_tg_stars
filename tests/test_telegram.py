from odoo.tests import common, tagged # Ensure these are present
from odoo import fields
from unittest.mock import patch
# Assuming TelegramService is available through an import like:
# from odoo.addons.telegram.services.telegram_service import TelegramService
# If not, the patch path might need adjustment or this import added.
# For now, the setUp uses it directly, implying it's in scope.

@tagged('post_install', '-at_install')
class TestTelegramIntegration(common.TransactionCase):

    def setUp(self):
        super().setUp()
        # self.telegram_service = TelegramService(self.env) # Assuming TelegramService is correctly imported/available
        self.bot = self.env['telegram.bot'].create({
            'name': 'Test Bot',
            'api_token': '123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11', # Example token
            'username': 'test_bot_user' # Example username
        })
        self.partner = self.env['res.partner'].create({'name': 'Test Partner for Telegram'})
        # Create telegram.info linking partner, bot, and providing a chat_id
        self.telegram_info = self.env['telegram.info'].create({
            'partner_id': self.partner.id,
            'bot_id': self.bot.id,
            'telegram_id': '1234567890', # Example Telegram User ID
            'chat_id': '987654321',    # Example Telegram Chat ID
            'telegram_username': 'testpartneruser'
        })
        
    def test_send_message(self):
        """تست ارسال پیام"""
        message = self.env['telegram.send.message.wizard'].create({
            'bot_id': self.bot.id,
            'chat_id': '123456789',
            'message': 'پیام تست'
        })
        
        result = message.action_send_message()
        self.assertEqual(result['type'], 'ir.actions.client')
        self.assertEqual(message.status, 'success') 

    def test_delete_webhook(self):
        """تست حذف webhook"""
        with self.env.cr.savepoint():
            service = self.env['telegram.service'].with_context(bot_id=self.bot.id).new()
            result = service.delete_webhook()
            self.assertTrue(result.get('ok')) 

    def test_set_webhook(self):
        """تست تنظیم webhook"""
        with self.env.cr.savepoint():
            service = self.env['telegram.service'].with_context(bot_id=self.bot.id).new()
            webhook_url = 'https://example.com/webhook'
            result = service.set_webhook(webhook_url)
            self.assertTrue(result.get('ok'))

    def test_scheduled_message_duplicate_prevention(self):
        """Test that scheduled messages are not re-sent if history for that scheduled_id already exists."""
        ScheduledMessage = self.env['telegram.scheduled.message']
        MessageHistory = self.env['telegram.message.history']

        # 1. Create and send a first scheduled message normally (for setup)
        scheduled_msg1 = ScheduledMessage.create({
            'name': 'Test Scheduled Msg 1 - Normal Send',
            'bot_id': self.bot.id,
            'message': '<p>Initial test message for scheduling.</p>',
            'domain': "[('id', '=', %s)]" % self.partner.id,
            'scheduled_date': fields.Datetime.now(),
            'state': 'queued'
        })
        ScheduledMessage._cron_send_scheduled_messages()

        self.assertEqual(scheduled_msg1.state, 'done', "Msg1 should be 'done' after cron processing.")
        history_msg1 = MessageHistory.search([
            ('scheduled_message_id', '=', scheduled_msg1.id),
            ('chat_id', '=', self.telegram_info.chat_id)
        ])
        self.assertEqual(len(history_msg1), 1, "One history record should exist for Msg1.")
        self.assertEqual(history_msg1.state, 'sent', "History for Msg1 should be 'sent'.")

        # 2. Core Test: Duplicate Prevention for scheduled_msg2
        scheduled_msg2 = ScheduledMessage.create({
            'name': 'Test Scheduled Msg 2 - Duplicate Check',
            'bot_id': self.bot.id,
            'message': '<p>Message for duplicate check.</p>',
            'domain': "[('id', '=', %s)]" % self.partner.id,
            'scheduled_date': fields.Datetime.now(),
            'state': 'queued'
        })

        # Manually create a 'sent' history record for scheduled_msg2 *before* cron runs for it.
        MessageHistory.create({
            'bot_id': self.bot.id,
            'chat_id': self.telegram_info.chat_id,
            'partner_id': self.partner.id,
            'scheduled_message_id': scheduled_msg2.id,
            'state': 'sent',
            'message': scheduled_msg2.message
        })

        # Mock the actual sending methods of the TelegramService.
        # Adjust 'odoo.addons.telegram.services.telegram_service.TelegramService'
        # if the module name or path to TelegramService is different.
        with patch('odoo.addons.telegram.services.telegram_service.TelegramService.send_message') as mock_send_message, \
             patch('odoo.addons.telegram.services.telegram_service.TelegramService.send_file') as mock_send_file:

            ScheduledMessage._cron_send_scheduled_messages()

            self.assertEqual(scheduled_msg2.state, 'done', "Msg2 should be 'done' (even if skipped as duplicate).")

            mock_send_message.assert_not_called()
            mock_send_file.assert_not_called()

            history_msg2_after_cron = MessageHistory.search([
                ('scheduled_message_id', '=', scheduled_msg2.id),
                ('chat_id', '=', self.telegram_info.chat_id)
            ])
            self.assertEqual(len(history_msg2_after_cron), 1, "Only one history record (the manually created one) should exist for Msg2.")
            self.assertEqual(history_msg2_after_cron.state, 'sent')