# Odoo Telegram Stars Integration (`odoo_tg_stars`)

## Overview
`odoo_tg_stars` is a comprehensive backend module for Odoo ERP designed to manage Telegram bots, orchestrate campaigns, and handle the Telegram ecosystem directly from the ERP interface. It acts as a critical infrastructure piece for businesses to automate communications, handle digital payments, and build interactive workflows without leaving their centralized system.

## Core Architecture & Features
Based on the internal structure of this module, it provides a robust set of features tailored for enterprise systemization:

* **Centralized Bot Management:** Native configuration and management of Telegram bots directly within Odoo (`models/telegram_bot.py`)[span_1](start_span)[span_1](end_span).
* **Secure Webhook Controllers:** Built-in endpoints to securely receive and process real-time updates from Telegram (`controllers/webhook.py`)[span_2](start_span)[span_2](end_span).
* **Interactive Workflows (Steps):** Advanced system to construct dynamic, multi-step bot interactions using custom logic handlers (`models/telegram_step.py`, `models/telegram_step_handlers.py`, `models/telegram_step_option.py`)[span_3](start_span)[span_3](end_span).
* **Campaign Orchestration:** Run, manage, and track targeted Telegram campaigns and their participants from the backend (`models/telegram_campaign.py`, `models/telegram_campaign_participant.py`)[span_4](start_span)[span_4](end_span).
* **Payment & Product Ecosystem:** Seamlessly link Telegram transactions and payments to internal Odoo products (`models/telegram_payment.py`, `models/telegram_product.py`)[span_5](start_span)[span_5](end_span).
* **Direct Communication Wizards:** Built-in Odoo wizards allowing administrators to send messages and files directly to Telegram users from the ERP (`wizards/send_message_wizard.py`, `wizards/telegram_send_file_wizard.py`)[span_6](start_span)[span_6](end_span).
* **High-Performance Caching:** Integration with Redis for optimized performance and state management (`tools/redis_config.py`)[span_7](start_span)[span_7](end_span).
* **Logging & History:** Complete tracking of user interactions, scheduled messages, and administrative logs for auditing (`models/telegram_log.py`, `models/telegram_message_history.py`, `models/telegram_scheduled_message.py`)[span_8](start_span)[span_8](end_span).

## Technical Stack
This module strictly follows Odoo's MVC architecture and incorporates backend API services (`services/telegram_service.py`) and granular security access rules (`security/telegram_security.xml`, `security/ir.model.access.csv`)[span_9](start_span)[span_9](end_span).

## Installation
1. Clone or download this repository into your Odoo `addons` directory.
2. If utilizing the Redis caching features, ensure your Redis server is active and properly configured.
3. Restart your Odoo server environment.
4. Enable **Developer Mode** in Odoo, click **Update Apps List**, search for `odoo_tg_stars`, and click **Install**.
