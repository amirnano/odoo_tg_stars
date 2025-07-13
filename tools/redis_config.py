import redis
from odoo import tools

def get_redis_client():
    """ایجاد اتصال redis"""
    redis_host = tools.config.get('redis_host', 'localhost')
    redis_port = int(tools.config.get('redis_port', 6379))
    redis_db = int(tools.config.get('redis_db', 0))
    redis_password = tools.config.get('redis_password', None)
    
    return redis.Redis(
        host=redis_host,
        port=redis_port,
        db=redis_db,
        password=redis_password,
        decode_responses=True,
        socket_timeout=5
    ) 