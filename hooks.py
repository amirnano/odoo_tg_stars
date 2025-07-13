def pre_init_hook(cr):
    """قبل از نصب ماژول اجرا می‌شود"""
    # ذخیره اطلاعات موجود
    cr.execute("""
        CREATE TABLE IF NOT EXISTS telegram_info_backup AS 
        SELECT * FROM telegram_info;
    """)
    cr.execute("""
        CREATE TABLE IF NOT EXISTS telegram_campaign_participant_backup AS 
        SELECT * FROM telegram_campaign_participant;
    """)

def post_init_hook(cr, registry):
    """بعد از نصب ماژول اجرا می‌شود"""
    # بازگرداندن اطلاعات
    cr.execute("""
        INSERT INTO telegram_info 
        SELECT * FROM telegram_info_backup 
        ON CONFLICT DO NOTHING;
    """)
    cr.execute("""
        INSERT INTO telegram_campaign_participant 
        SELECT * FROM telegram_campaign_participant_backup 
        ON CONFLICT DO NOTHING;
    """)

def uninstall_hook(cr, registry):
    """حذف داده‌های مربوط به مدل‌های حذف شده"""
    # ذخیره اطلاعات قبل از حذف
    cr.execute("""
        CREATE TABLE IF NOT EXISTS telegram_info_uninstall_backup AS 
        SELECT * FROM telegram_info;
    """)
    cr.execute("""
        CREATE TABLE IF NOT EXISTS telegram_campaign_participant_uninstall_backup AS 
        SELECT * FROM telegram_campaign_participant;
    """) 