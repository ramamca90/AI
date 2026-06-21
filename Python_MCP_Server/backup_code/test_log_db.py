import os
from datetime import datetime
from configparser import ConfigParser


from logger_helper import get_logger
from postgresql_db_helper import PostgreSQLDatabaseHelper

DB_INI_FILE = "E:\\__playground__\\python\\gen_ai_app\\src\\gen_ai_app.cfg"

class TestLogDB:

    def __init__(self):
        self.db_conn = None
        
        self.date_now = datetime.now()
        self.program_name = os.path.basename(__file__)

        self.logger = self.create_logger()


    def read_config(self):

        # create a parser
        parser = ConfigParser()
        # read config file
        parser.read(DB_INI_FILE)
    
        # get section, default to postgresql
        gen_ai_app_parameters = {}

        if parser.has_section('gen_ai_app'):
            params = parser.items('gen_ai_app')
            for param in params:
                gen_ai_app_parameters[param[0]] = param[1]
        else:
            raise Exception(f"{DB_INI_FILE} file not exists or Section 'gen_ai_app' not found")
        
        return gen_ai_app_parameters
    

    def create_logger(self):
        # Implement your test logic here
        self.log_path = self.read_config()['log_path']

        log_name = self.program_name.split('.')[0]
        log_file = os.path.join(self.log_path, f"{log_name}_{self.date_now.strftime('%Y%m%d')}.log")
        
        return get_logger(log_file=log_file, log_name=log_name)
    
    
    def connect_database(self):
        self.db_conn = PostgreSQLDatabaseHelper(self.logger)
        self.db_cusor = self.db_conn.connect().create_cursor_instance()


    def main(self):
        self.logger.info(f"{self.program_name} started..")

        self.connect_database()

        self.logger.info(f"{self.program_name} completed..")


        test_query = "SELECT * FROM employees.salary LIMIT 5;"
        self.db_cusor.db_execute(test_query)

        print(self.db_cusor.db_fetch_all())
        

if __name__ == "__main__":
    test_log_db = TestLogDB()
    test_log_db.main()