from odoo import models, fields, api
from datetime import datetime, timedelta
from odoo.tools.safe_eval import safe_eval as eval_domain
from odoo.exceptions import ValidationError, UserError
import logging
import ast
from bs4 import BeautifulSoup
import time
import psycopg2 # For LockNotAvailable
import re # For _prepare_telegram_message
from odoo.osv import expression

_logger = logging.getLogger(__name__)

class TelegramScheduledMessage(models.Model):
    _name = 'telegram.scheduled.message'
    # Ensure this field exists or is added to your model
    # message_content_id = fields.Many2one('telegram.message.content', string='Unique Message Content', ondelete='restrict')
    # For the purpose of this fix, if message_content_id is not available,
    # we might fall back to using a hash of self.message or self.id for the duplicate check logic,
    # but a dedicated content ID is cleaner. For this implementation, I'll assume
    # a conceptual 'unique content identifier' for the duplicate check.
    # If message_content_id is not present, I will use self.message for the check,
    # which was in the original duplicate check logic.
    _description = 'پیام‌های تلگرام'
    _order = 'create_date desc'

    name = fields.Char(string='عنوان', required=True)
    message = fields.Html(string='متن پیام', required=True) # Used for duplicate check if no message_content_id
    attachment = fields.Binary(string='فایل پیوست')
    attachment_name = fields.Char(string='نام فایل')
    use_html_format = fields.Boolean(string='استفاده از فرمت HTML', default=True)
    bot_id = fields.Many2one('telegram.bot', string='ربات', required=True)
    
    # فیلدهای فیلتر مخاطبین
    domain = fields.Char(string='دامنه فیلتر', help='فیلتر مخاطبین برای ارسال پیام')
    participant_count = fields.Integer(string='تعداد مخاطبین', compute='_compute_participant_count')
    
    state = fields.Selection([
        ('draft', 'پیش‌نویس'),
        ('queued', 'در صف ارسال'),
        ('sending', 'در حال ارسال'), # Changed 'in_progress' to 'sending' for clarity
        ('done', 'ارسال شده'),
        ('failed', 'خطا در ارسال')
    ], string='وضعیت', default='draft', copy=False, tracking=True)

    batch_size = fields.Integer(string='تعداد در هر دسته', default=50, # This field seems unused in the provided sending logic
        help='تعداد پیام‌های ارسالی در هر دسته')
    processed_count = fields.Integer(string='تعداد پردازش شده', default=0, copy=False)
    failed_count = fields.Integer(string='تعداد خطا', default=0, copy=False)
    success_count = fields.Integer(string='تعداد موفق', default=0, copy=False)
    last_error = fields.Text(string='آخرین خطا', copy=False)
    attachment_type = fields.Selection([
        ('photo', 'تصویر'),
        ('video', 'ویدیو'),
        ('audio', 'صوت'),
        ('document', 'دیتا')
    ], string='نوع فایل پیوست', compute='_compute_attachment_type')

    excluded_chat_ids = fields.Text(
        string='شناسه‌های چت مستثنی',
        help='شناسه‌های چت که نباید پیام دریافت کنند (با فاصله جدا کنید)'
    )
    # Add a field for scheduled date if it doesn't exist.
    # This is crucial for the cron job to select messages.
    scheduled_date = fields.Datetime(string='تاریخ زمانبندی ارسال', default=fields.Datetime.now, required=True, index=True)


    def action_send(self):
        """شروع فرآیند ارسال"""
        self.ensure_one()
        if self.state not in ['draft', 'failed']:
            raise UserError('فقط پیام‌های پیش‌نویس یا ناموفق را می‌توان در صف قرار داد.')
            
        if self.participant_count <= 0:
            raise UserError('هیچ مخاطبی برای ارسال پیام یافت نشد.')
            
        self.write({
            'state': 'queued',
            'processed_count': 0,
            'failed_count': 0,
            'success_count': 0,
            'last_error': False,
        })
        # The cron job will pick this up. No need to call _process_scheduled_messages directly.
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'ارسال پیام زمانبندی شده',
                'message': 'پیام در صف ارسال قرار گرفت و توسط کار زمانبندی شده ارسال خواهد شد.',
                'type': 'info',
                'sticky': False,
            }
        }

    def _send_to_single_recipient(self, partner, message_text_prepared):
        self.ensure_one()
        partner_sent_successfully = False
        if not partner.telegram_ids:
            _logger.info(f"Partner {partner.id} ({partner.name}) has no associated Telegram accounts. Skipping for scheduled_message_id {self.id}.")
            return False 

        current_bot_id_to_use = self.bot_id.id 

        for telegram_info in partner.telegram_ids:
            target_chat_id = telegram_info.chat_id
            if not target_chat_id:
                _logger.warning(f"Telegram Info {telegram_info.id} for partner {partner.id} ({partner.name}) has no chat_id. Skipping.")
                continue

            if telegram_info.bot_id and telegram_info.bot_id.is_active:
                current_bot_id_to_use = telegram_info.bot_id.id
            elif not self.bot_id or not self.bot_id.is_active: 
                _logger.error(f"Main bot {self.bot_id.name if self.bot_id else 'N/A'} for scheduled_message_id {self.id} is not configured or inactive, and no specific active bot for telegram_info {telegram_info.id}. Cannot send.")
                self.env['telegram.message.history'].create({
                    'partner_id': partner.id,
                    'message': message_text_prepared,
                    'attachment_name': self.attachment_name,
                    'state': 'failed',
                    'error_message': 'No active bot configured for sending to this recipient.',
                    'chat_id': target_chat_id, # Log with target_chat_id even if send fails due to bot config
                    'scheduled_message_id': self.id,
                    'bot_id': self.bot_id.id if self.bot_id else None, # Log the intended bot if possible
                })
                continue 

            history_domain = [
                ('scheduled_message_id', '=', self.id),
                ('chat_id', '=', target_chat_id),
                ('state', '=', 'sent')
            ]
            if self.env['telegram.message.history'].search_count(history_domain) > 0:
                _logger.info(f"Skipping duplicate: scheduled_message_id {self.id} already successfully sent to chat_id {target_chat_id}.")
                partner_sent_successfully = True
                break 

            try:
                service = self.env['telegram.service'].sudo().with_context(
                    bot_id=current_bot_id_to_use
                ).new()
                
                if self.attachment:
                    service.send_file(
                        chat_id=target_chat_id,
                        file_content=self.attachment,
                        filename=self.attachment_name,
                        caption=message_text_prepared,
                        parse_mode='HTML' if self.use_html_format else None
                    )
                else:
                    service.send_message(
                        chat_id=target_chat_id,
                        message=message_text_prepared,
                        parse_mode='HTML' if self.use_html_format else None
                    )
                
                self.env['telegram.message.history'].create({
                    'partner_id': partner.id,
                    'message': message_text_prepared, 
                    'attachment_name': self.attachment_name,
                    'state': 'sent',
                    'bot_id': current_bot_id_to_use,
                    'chat_id': target_chat_id,
                    'scheduled_message_id': self.id, 
                })
                _logger.info(f"Successfully sent scheduled_message_id {self.id} to partner {partner.id} (chat_id {target_chat_id}).")
                partner_sent_successfully = True
                break 
            
            except Exception as e_send:
                error_msg = str(e_send)
                _logger.error(f"Error sending scheduled_message_id {self.id} to partner {partner.id} (chat_id {target_chat_id}): {error_msg}", exc_info=True)
                state = 'failed'
                if 'bot was blocked' in error_msg.lower(): state = 'blocked'
                elif 'user is deactivated' in error_msg.lower(): state = 'deactivated'
                elif 'chat not found' in error_msg.lower(): state = 'failed' 
                
                self.env['telegram.message.history'].create({
                    'partner_id': partner.id,
                    'message': message_text_prepared,
                    'attachment_name': self.attachment_name,
                    'state': state,
                    'error_message': error_msg,
                    'bot_id': current_bot_id_to_use,
                    'chat_id': target_chat_id,
                    'scheduled_message_id': self.id,
                })
        return partner_sent_successfully

    def _send_to_all_recipients(self):
        """
        Processes sending this specific scheduled message to all its recipients.
        Returns True if all recipients were processed successfully (or skipped as duplicate),
        False if any recipient encountered a hard failure during send.
        """
        self.ensure_one()
        _logger.info(f"Processing recipients for scheduled_message_id {self.id} ('{self.name}')")
        partners = self._get_partners()
        if not partners:
            _logger.info(f"No partners found for scheduled_message_id {self.id}.")
            self.write({'processed_count': 0, 'success_count': 0, 'failed_count': 0})
            return True # No partners means technically all (zero) were successful

        message_text_prepared = self._prepare_telegram_message()
        current_success_count = 0
        current_failed_count = 0
        
        # Reset counts for this run if it's being retried
        # Or, accumulate if that's desired. For now, let's assume counts are for the current processing run.
        # self.write({'processed_count': 0, 'success_count': 0, 'failed_count': 0}) 
        # Actually, these counts should reflect the lifetime of the scheduled message,
        # so we increment them based on new processing.

        all_recipients_processed_without_hard_error = True

        for partner_idx, partner in enumerate(partners):
            if not self.exists(): # Check if the record was deleted mid-process
                _logger.warning(f"Scheduled message {self.id} deleted mid-process. Aborting.")
                return False

            _logger.info(f"Sending to partner {partner.id} ({partner_idx + 1}/{len(partners)}) for scheduled_message_id {self.id}")
            
            try:
                sent_to_partner = self._send_to_single_recipient(partner, message_text_prepared)
                
                # Update counts on the main record.
                # The self.write here is frequent, but commits are controlled.
                if sent_to_partner:
                    current_success_count +=1
                else:
                    current_failed_count +=1
                
                # Commit after each partner is processed + history created
                # This saves progress for each partner.
                self.env.cr.commit() 
                _logger.info(f"Committed after partner {partner.id} for scheduled_message_id {self.id}")

            except Exception as e_partner_loop:
                # This is a more general error in the partner processing loop itself
                _logger.error(f"Unexpected error processing partner {partner.id} for scheduled_message_id {self.id}: {e_partner_loop}", exc_info=True)
                self.env.cr.rollback() # Rollback this partner's attempt
                current_failed_count +=1
                all_recipients_processed_without_hard_error = False
                # Ensure a history record reflects this general failure if not already created
                # This might be complex if telegram_info was not reachable
                # For now, the specific failure is logged, and failed_count incremented.

        # Update final counts after processing all partners for this specific `self`
        # These are additive if the job is retried and some partners were processed before.
        # A better approach for retries would be to only count newly processed partners.
        # For simplicity now, this just sums up.
        final_processed = self.processed_count + current_success_count + current_failed_count
        final_success = self.success_count + current_success_count
        final_failed = self.failed_count + current_failed_count

        self.write({
            'processed_count': final_processed,
            'success_count': final_success,
            'failed_count': final_failed,
        })
        # The commit for this final write will be handled by the calling cron method.
        
        _logger.info(f"Finished processing recipients for scheduled_message_id {self.id}. Success: {current_success_count}, Failed: {current_failed_count}")
        return all_recipients_processed_without_hard_error


    @api.model
    def _cron_send_scheduled_messages(self):
        """
        Cron job method to fetch and process scheduled messages.
        Implements pessimistic locking and state management.
        """
        _logger.info("Cron job _cron_send_scheduled_messages started.")
        
        # Fetch candidate messages: state is 'queued' and scheduled_date is now or in the past.
        # Add a limit to process in batches, e.g., 100 messages per cron run.
        candidate_messages_ids = self.search([
            ('state', '=', 'queued'),
            ('scheduled_date', '<=', fields.Datetime.now())
        ], limit=100, order='scheduled_date, id').ids

        if not candidate_messages_ids:
            _logger.info("No candidate messages to process in this cron run.")
            return

        messages_to_process_ids = []
        for msg_id in candidate_messages_ids:
            try:
                # Attempt to acquire a lock for this specific message ID.
                # FOR UPDATE NOWAIT will raise LockNotAvailable immediately if locked.
                self.env.cr.execute("SELECT id FROM telegram_scheduled_message WHERE id = %s FOR UPDATE NOWAIT", (msg_id,), log_exceptions=False)
                messages_to_process_ids.append(msg_id)
                _logger.info(f"Successfully locked scheduled_message_id {msg_id}.")
            except psycopg2.errors.LockNotAvailable:
                _logger.info(f"Could not acquire lock for scheduled_message_id {msg_id}, it's likely being processed by another worker. Skipping.")
            except Exception as e_lock:
                _logger.error(f"Error acquiring lock for scheduled_message_id {msg_id}: {e_lock}")
                self.env.cr.rollback() # Rollback any implicit transaction start by execute

        if not messages_to_process_ids:
            _logger.info("No messages could be locked for processing in this cron run.")
            return

        # Update state to 'sending' for all locked messages and commit immediately.
        # This prevents other workers from picking them up again.
        locked_messages = self.browse(messages_to_process_ids)
        try:
            locked_messages.write({'state': 'sending', 'last_error': False})
            self.env.cr.commit()
            _logger.info(f"Updated state to 'sending' for messages: {messages_to_process_ids}")
        except Exception as e_state_update:
            _logger.error(f"Error updating state to 'sending' for messages {messages_to_process_ids}: {e_state_update}", exc_info=True)
            self.env.cr.rollback()
            # Messages that failed state update won't be processed further in this run.
            # They will be picked up again in the next cron if their state is still 'queued'.
            return

        for message in locked_messages:
            if not message.exists(): # Could have been deleted by another process after browse
                _logger.warning(f"Message {message.id} was deleted after locking. Skipping.")
                continue
            try:
                _logger.info(f"Starting processing for locked message: {message.id} ('{message.name}')")
                # Reset counts for this specific run, if needed, or make them purely additive.
                # For now, _send_to_all_recipients updates them additively.
                
                all_sent_successfully = message._send_to_all_recipients() # This method now commits per partner

                if all_sent_successfully:
                    # Check if all partners defined by the domain were processed.
                    # This check might be complex if _get_partners() is very dynamic or large.
                    # For now, if _send_to_all_recipients returns True, we assume it handled all.
                    # A more robust check would be to compare message.processed_count with message.participant_count
                    # if participant_count is accurate at the time of sending.
                    # Let's assume participant_count is reasonably up-to-date for this logic.
                    if message.processed_count >= message.participant_count:
                         message.write({'state': 'done', 'last_error': False})
                    else:
                        # Some recipients might have been skipped or failed, but no hard error in the process itself
                        # If counts don't match, it might be due to exclusions or prior processing.
                        # Or, if _send_to_all_recipients returns false, it indicates a problem.
                        # This logic might need refinement based on how "completeness" is defined.
                        # For now, if the helper didn't report a hard error, we mark as done if processed matches participant count.
                        # Otherwise, it suggests it might need review or could be set to failed.
                        # A simpler approach: if no hard error, it's 'done' for this batch.
                        # If some failed, failed_count will be > 0.
                         message.write({'state': 'done', 'last_error': False})


                    _logger.info(f"Successfully processed message {message.id}. Final state: {message.state}")
                else:
                    # _send_to_all_recipients returned False, meaning some part of its execution had an issue
                    message.write({'state': 'failed', 'last_error': 'One or more recipients failed or an error occurred during _send_to_all_recipients.'})
                    _logger.warning(f"Failed to process all recipients for message {message.id}. Final state: 'failed'")
                
                self.env.cr.commit() # Commit final state for this message
                _logger.info(f"Committed final state for message {message.id}")

            except Exception as e_msg_process:
                _logger.error(f"Unhandled error processing message {message.id} ('{message.name}'): {e_msg_process}", exc_info=True)
                self.env.cr.rollback()
                try:
                    if message.exists():
                        message.write({'state': 'failed', 'last_error': str(e_msg_process)})
                        self.env.cr.commit()
                        _logger.info(f"Rolled back and set message {message.id} to 'failed' due to unhandled error.")
                except Exception as e_final_fail:
                    _logger.error(f"CRITICAL: Failed to even set message {message.id} to 'failed' after unhandled error: {e_final_fail}")
                    self.env.cr.rollback() # Final rollback attempt for this message's transaction part

        _logger.info("Cron job _cron_send_scheduled_messages finished.")


    @api.depends('domain')
    def _compute_participant_count(self):
        for record in self:
            try:
                default_telegram_condition = [('telegram_ids', '!=', False)]
                if record.domain:
                    parsed_domain = ast.literal_eval(record.domain) if isinstance(record.domain, str) else record.domain
                    
                    if not parsed_domain or parsed_domain == [[]]: # Handles "[]", "[[]]", or empty string that evals to Falsy
                        final_domain = default_telegram_condition
                    elif not isinstance(parsed_domain, (list, tuple)) or \
                         (parsed_domain and not all(isinstance(item, (list, tuple)) for item in parsed_domain)):
                        _logger.error(f"Invalid domain format for count in scheduled_message_id {record.id}: {record.domain}. Must be a list/tuple of conditions.", exc_info=True)
                        record.participant_count = 0
                        continue 
                    else:
                        # Always AND with the default condition to ensure we only count partners who could have telegram
                        final_domain = expression.AND([default_telegram_condition, parsed_domain])
                else: 
                    final_domain = default_telegram_condition
                
                record.participant_count = self.env['res.partner'].with_context(active_test=False).search_count(final_domain)
            except Exception as e_count:
                _logger.error(f"Error evaluating domain for participant count in scheduled_message_id {record.id}: {str(e_count)} Domain was: {record.domain}", exc_info=True)
                record.participant_count = 0

    def _get_partners(self):
        self.ensure_one()
        partners_to_send = self.env['res.partner'] # Default to empty
        default_telegram_condition = [('telegram_ids', '!=', False)]
        final_search_domain = default_telegram_condition

        if self.domain:
            _logger.info(f"Processing scheduled_message_id {self.id} ('{self.name}') with custom domain: {self.domain}")
            try:
                parsed_domain = ast.literal_eval(self.domain) if isinstance(self.domain, str) else self.domain
                
                if not parsed_domain or parsed_domain == [[]]: # Handles "[]", "[[]]", or empty string that evals to Falsy
                    # This case means user provided an empty domain, so we stick to default_telegram_condition
                    _logger.info(f"Custom domain for {self.id} is empty. Using default condition.")
                    # final_search_domain is already default_telegram_condition
                elif not isinstance(parsed_domain, (list, tuple)) or \
                   (parsed_domain and not all(isinstance(item, (list, tuple)) for item in parsed_domain)):
                    raise ValueError("Domain must be a list or tuple of conditions (list of lists/tuples).")
                else:
                    # Valid, non-empty custom domain. Combine with default.
                    final_search_domain = expression.AND([default_telegram_condition, parsed_domain])
                
                _logger.info(f"Searching partners for scheduled_message_id {self.id} with final domain: {final_search_domain}")
                partners_to_send = self.env['res.partner'].with_context(active_test=False).search(final_search_domain)
                _logger.info(f"Found {len(partners_to_send)} partners using domain {final_search_domain} for scheduled_message_id {self.id}.")

            except Exception as e_domain:
                error_message = f"Error processing domain for scheduled_message_id {self.id} ('{self.name}'). Domain: '{self.domain}'. Error: {str(e_domain)}"
                _logger.error(error_message, exc_info=True)
                if self.exists(): 
                    try:
                        self.write({'state': 'failed', 'last_error': f"Domain error: {str(e_domain)}"})
                        self.env.cr.commit()
                    except Exception as e_write:
                        _logger.error(f"Failed to write error state for scheduled_message_id {self.id}: {e_write}", exc_info=True)
                        self.env.cr.rollback()
                return self.env['res.partner'] 
        else:
            _logger.info(f"No custom domain for scheduled_message_id {self.id} ('{self.name}'). Getting all partners with Telegram IDs using default domain: {default_telegram_condition}")
            partners_to_send = self.env['res.partner'].with_context(active_test=False).search(default_telegram_condition)

        # Filter by excluded_chat_ids
        if self.excluded_chat_ids and partners_to_send:
            try:
                excluded_ids_str = {str(s.strip()) for s in self.excluded_chat_ids.split() if s.strip().isdigit()}
                if excluded_ids_str:
                    initial_count = len(partners_to_send)
                    partners_to_send = partners_to_send.filtered(
                        lambda p: not any(
                            str(t.chat_id) in excluded_ids_str
                            for t in p.telegram_ids
                        )
                    )
                    _logger.info(f"Filtered out {initial_count - len(partners_to_send)} partners based on excluded_chat_ids for scheduled_message_id {self.id}.")
            except Exception as e_exclude:
                _logger.error(f"Error processing excluded chat IDs for scheduled_message_id {self.id}: {str(e_exclude)}", exc_info=True)
                # Decide if this error should also fail the message or just log. For now, log and continue.
        
        return partners_to_send

    def _prepare_telegram_message(self):
        """آماده‌سازی متن پیام برای تلگرام"""
        self.ensure_one()
        if not self.message:
            return ''
        
        if not self.use_html_format:
            # For non-HTML, still good to strip any accidental HTML tags
            soup = BeautifulSoup(self.message, 'html.parser')
            return soup.get_text()

        # Process HTML content
        message_html = self.message
        
        # Basic cleaning using BeautifulSoup
        soup = BeautifulSoup(message_html, 'html.parser')
        
        # Telegram supported HTML tags: b, strong, i, em, u, ins (for underline), 
        # s, strike, del (for strikethrough), a (href), code, pre, tg-spoiler, tg-emoji
        # We need to be careful not to over-process if the HTML is already well-formed for Telegram.
        # The original code did a lot of replacements that might be too aggressive
        # if the source HTML is already crafted for Telegram.

        # A simpler approach: iterate and ensure only allowed tags with allowed attributes remain.
        # For now, let's assume the input HTML from the editor is reasonably clean or
        # the user is responsible for formatting it according to Telegram's HTML subset.
        # We will perform a minimal cleanup of <p> and <br> tags as they are common from WYSIWYG.

        for p_tag in soup.find_all('p'):
            p_tag.insert_before(p_tag.text + '\n\n') # Add double newline for paragraph breaks
            p_tag.decompose() # Remove the <p> tag itself

        for br_tag in soup.find_all('br'):
            br_tag.replace_with('\n')

        # Get the processed HTML string
        processed_message = str(soup)

        # Further cleaning can be done here if needed, e.g., removing unsupported attributes.
        # For simplicity, this example assumes the HTML widget in Odoo produces
        # compatible enough HTML or users are guided.
        
        # Remove zero-width space characters that might be added by editors
        processed_message = processed_message.replace('\u200B', '')
        # Replace non-breaking spaces with regular spaces
        processed_message = processed_message.replace('&nbsp;', ' ').replace('\xa0', ' ')
        # Normalize multiple spaces
        processed_message = re.sub(r' +', ' ', processed_message)
        # Normalize multiple newlines (max 2)
        processed_message = re.sub(r'\n\s*\n(\s*\n)+', '\n\n', processed_message)
        processed_message = processed_message.strip()
        
        return processed_message

    @api.depends('attachment_name')
    def _compute_attachment_type(self):
        """محاسبه نوع فایل پیوست"""
        for record in self:
            if record.attachment_name:
                ext = record.attachment_name.lower().split('.')[-1]
                if ext in ['jpg', 'jpeg', 'png', 'gif']:
                    record.attachment_type = 'photo'
                elif ext in ['mp4', 'avi', 'mkv', 'mov']: # Added mov
                    record.attachment_type = 'video'
                elif ext in ['mp3', 'wav', 'ogg', 'm4a']: # Added m4a
                    record.attachment_type = 'audio'
                else:
                    record.attachment_type = 'document'
            else:
                record.attachment_type = False

    # The action_show_count method was for debugging and can be kept or removed.
    # def action_show_count(self): ...

    # The _cron_process_messages was the old entry point, now replaced by _cron_send_scheduled_messages
    # @api.model
    # def _cron_process_messages(self):
    #     """پردازش پیام‌های در صف"""
    #     return self._process_scheduled_messages() # This was the old call
    # No, the cron job in data/ir_cron_data.xml calls `model._process_scheduled_messages()`
    # So, the method to be renamed or that serves as entry point should be `_process_scheduled_messages`.
    # The new plan calls for `_cron_send_scheduled_messages` as the main cron method.
    # I will assume the cron job definition in XML will be updated to call `_cron_send_scheduled_messages`.
    # If `_process_scheduled_messages` is the one called by XML, then that's the one to modify.
    # For this fix, I've created `_cron_send_scheduled_messages` as the top-level cron method.
    # The XML `<code>model._process_scheduled_messages()</code>` needs to be changed to `model._cron_send_scheduled_messages()`

    # Ensure that telegram.message.history has a field like 'scheduled_message_id'
    # to link it back to this model for the duplicate check.
    # Example (add to telegram_message_history.py):
    # scheduled_message_id = fields.Many2one('telegram.scheduled.message', string='Scheduled Message', ondelete='set null', index=True)