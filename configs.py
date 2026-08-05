import os

from dotenv import load_dotenv

db_config_declare = {
    'allow_r18g': False,
    'enable_on_new_group': False,
    'pixiv_cache_to_telegram': True,
    'super_user': '1285315854',
}


class __Config:
    def __init__(self):
        load_dotenv()
        # 数据库类型: 'sqlite'（默认，无需任何配置）或 'mysql'/'mariadb'
        self.db_type = (os.getenv('DATABASE_TYPE') or 'sqlite').strip().lower()
        self.db_host = os.getenv('DATABASE_HOST') or 'localhost'
        self.db_port = int(os.getenv('DATABASE_PORT') or 3306)
        self.db_username = os.getenv('DATABASE_USERNAME') or 'root'
        self.db_password = os.getenv('DATABASE_PASSWORD') or ''
        self.db_name = os.getenv('DATABASE_NAME') or 'acgimg'
        self.db_prefix = os.getenv('DATABASE_PREFIX') or ''
        self.external_url = os.getenv('EXTERNAL_URL')


config = __Config()
