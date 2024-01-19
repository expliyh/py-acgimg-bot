import os

from dotenv import load_dotenv

__env_path = '.env'


class __Config:
    def __init__(self):
        load_dotenv()
        self.db_host = os.getenv('DATABASE_HOST')
        self.db_port = int(os.getenv('DATABASE_PORT'))
        self.db_username = os.getenv('DATABASE_USERNAME')
        self.db_password = os.getenv('DATABASE_PASSWORD')
        self.db_name = os.getenv('DATABASE_NAME')
        self.db_prefix = os.getenv('DATABASE_PREFIX')


config = __Config()
