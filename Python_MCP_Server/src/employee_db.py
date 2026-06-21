import os
from datetime import datetime
from configparser import ConfigParser

from logger_helper import get_logger
from postgresql_db_helper import PostgreSQLDatabaseHelper

DB_INI_FILE = "E:\\__playground__\\python\\gen_ai_app\\src\\gen_ai_app.cfg"

class EmployeeDB:
    """Encapsulates PostgreSQL operations for the employees schema with logging."""

    def __init__(self):
        """
        Initialize the EmployeeDB instance.
        Sets up placeholders for database connection, current date, program name, and logger.
        """
        self.db_conn = None
        self.date_now = datetime.now()
        self.program_name = os.path.basename(__file__)
        self.logger = self.create_logger()


    def read_config(self):
        """
        Read database and application configuration from the cfg file.

        Returns:
            dict: Dictionary of configuration parameters under the 'gen_ai_app' section.

        Raises:
            Exception: If the config file does not exist or the section 'gen_ai_app' is missing.
        """
        parser = ConfigParser()
        parser.read(DB_INI_FILE)
    
        gen_ai_app_parameters = {}
        if parser.has_section('gen_ai_app'):
            params = parser.items('gen_ai_app')
            for param in params:
                gen_ai_app_parameters[param[0]] = param[1]
        else:
            raise Exception(f"{DB_INI_FILE} file not exists or Section 'gen_ai_app' not found")
        
        return gen_ai_app_parameters

    def create_logger(self):
        """
        Create and configure a logger for the application.

        Returns:
            logging.Logger: Configured logger instance.
        """
        self.log_path = self.read_config()['log_path']

        log_name = self.program_name.split('.')[0]
        log_file = os.path.join(self.log_path, f"{log_name}_{self.date_now.strftime('%Y%m%d')}.log")

        return get_logger(log_file=log_file, log_name=log_name)
    
    def connect_database(self):
        """
        Establish a connection to the PostgreSQL database using PostgreSQLDatabaseHelper.
        Creates a cursor instance for executing queries.
        """
        self.db_conn = PostgreSQLDatabaseHelper(self.logger)
        self.db_cursor = self.db_conn.connect().create_cursor_instance()

    # --- SELECT tools ---
    def get_employee_by_partial_name(self, name_pattern: str) -> str:
        """
        Retrieve employee details by partial name match.
    
        Args:
            name_pattern (str): A substring or pattern to match against
                                first_name or last_name (SQL LIKE syntax).
    
        Returns:
            str: List of matching employees with ID, full name, gender, and hire date,
                 or 'No employees found' if none match.
        """
        self.logger.info(f"Searching employees by partial name: {name_pattern}")
    
        sql_query = """
            SELECT id, first_name, last_name, gender, hire_date
            FROM employees.employee
            WHERE first_name ILIKE %(pattern)s
               OR last_name ILIKE %(pattern)s
            ORDER BY id
        """
        sql_parms = {"pattern": f"%{name_pattern}%"}
    
        self.db_cursor.db_execute(sql_query, sql_parms)
        rows = self.db_cursor.db_fetch_all()
    
        self.logger.info("Partial name search results: %s", rows)
    
        if rows:
            return "\n".join([f"ID {r[0]}: {r[1]} {r[2]}, Gender {r[3]}, Hired {r[4]}" for r in rows])
        else:
            return "No employees found"

    def get_employee(self, employee_id: int) -> str:
        """
        Retrieve basic employee details by ID.

        Args:
            employee_id (int): Employee ID.

        Returns:
            str: Employee's first name, last name, gender, and hire date,
                 or 'Employee not found' if no record exists.
        """
        self.logger.info(f"Fetching employee details for ID={employee_id}")

        sql_query = """
                    SELECT first_name, last_name, gender, hire_date
                    FROM   employees.employee
                    WHERE  id = %(employee_id)s
                """
        sql_parms = {"employee_id": employee_id}
        self.db_cursor.db_execute(sql_query, sql_parms)
        row = self.db_cursor.db_fetch_one()

        if row:
            self.logger.info("Employee record: %s", row)
            return f"{row[0]} {row[1]}, Gender {row[2]}, Hired {row[3]}"
        
        self.logger.warning(f"Employee {employee_id} not found")
        return "Employee not found"
    
    def get_salary_history(self, employee_id: int) -> str:
        """
        Retrieve salary history for an employee.

        Args:
            employee_id (int): Employee ID.

        Returns:
            str: List of salary records with amount and date ranges,
                 or 'No salary records' if none exist.
        """
        self.logger.info(f"Fetching salary history for ID={employee_id}")

        sql_query = """
            SELECT amount, from_date, to_date
            FROM employees.salary
            WHERE employee_id = %(employee_id)s
            ORDER BY from_date DESC
            """
        sql_parms = {"employee_id": employee_id}
        self.db_cursor.db_execute(sql_query, sql_parms)
        rows = self.db_cursor.db_fetch_all()

        self.logger.info("Salary rows: %s", rows)
        return "\n".join([f"{amt} from {fd} to {td}" for amt, fd, td in rows]) or "No salary records"
    
    # --- UPDATE tools ---
    def update_employee_name(self, employee_id: int, first_name: str, last_name: str) -> str:
        """
        Update an employee's first and last name.

        Args:
            employee_id (int): Employee ID.
            first_name (str): New first name.
            last_name (str): New last name.

        Returns:
            str: Confirmation message after update.
        """
        self.logger.info(f"Updating employee {employee_id} name to {first_name} {last_name}")

        sql_query = """
            UPDATE employees.employee
            SET    first_name = %(first_name)s, last_name = %(last_name)s
            WHERE  id = %(employee_id)s
        """
        sql_parms = {
            "first_name": first_name,
            "last_name": last_name,
            "employee_id": employee_id
        }
        self.db_cursor.db_execute(sql_query, sql_parms)
        self.db_cursor.db_commit()

        self.logger.info(f"Update committed for employee {employee_id}")
        return f"Updated employee {employee_id} name to {first_name} {last_name}"
    
    def update_salary(self, employee_id: int, amount: int, from_date: str, to_date: str) -> str:
        """
        Update salary record for an employee by closing out the current
        salary row and inserting a new salary row.

        Args:
            employee_id (int): Employee ID.
            amount (int): New salary amount.
            from_date (str): Start date of the new salary record.
            to_date (str): End date of the new salary record.

        Returns:
            str: Confirmation message after update.
        """
        self.logger.info(f"Updating salary for employee {employee_id} to {amount}")

        sql_query_close = """
            UPDATE employees.salary
            SET    to_date = %(from_date)s
            WHERE  employee_id = %(employee_id)s
              AND  from_date = (
                       SELECT MAX(from_date)
                       FROM   employees.salary
                       WHERE  employee_id = %(employee_id)s
                   )
        """
        sql_query_insert = """
            INSERT INTO employees.salary (employee_id, amount, from_date, to_date)
            VALUES (%(employee_id)s, %(amount)s, %(from_date)s, %(to_date)s)
        """
        sql_parms = {
            "amount": amount,
            "to_date": to_date,
            "employee_id": employee_id,
            "from_date": from_date
        }

        self.db_cursor.db_execute(sql_query_close, sql_parms)
        if self.db_cursor.rowcount == 0:
            self.logger.warning(
                f"No existing salary row found to close for employee {employee_id}; "
                f"proceeding to insert new row anyway"
            )

        self.db_cursor.db_execute(sql_query_insert, sql_parms)
        if self.db_cursor.rowcount != 1:
            self.logger.error(
                f"Expected 1 row inserted for employee {employee_id}, "
                f"got {self.db_cursor.rowcount}"
            )

        self.db_cursor.db_commit()

        self.logger.info(f"Update committed for employee {employee_id}")
        return f"Updated salary for employee {employee_id} to {amount}"

    def get_titles(self, employee_id: int) -> str:
        """
        Retrieve job titles (roles) for an employee.

        Args:
            employee_id (int): Employee ID.

        Returns:
            str: List of titles with date ranges, or 'No titles found'.
        """
        self.logger.info(f"Fetching titles for employee {employee_id}")

        sql_query = """
            SELECT title, from_date, to_date
            FROM employees.title
            WHERE employee_id = %(employee_id)s
            ORDER BY from_date DESC
        """
        sql_parms = {"employee_id": employee_id}
        self.db_cursor.db_execute(sql_query, sql_parms)
        rows = self.db_cursor.db_fetch_all()

        self.logger.debug("Title rows: %s", rows)
        return "\n".join([f"{title} ({fd} → {td})" for title, fd, td in rows]) or "No titles found"

    def update_title(self, employee_id: int, title: str, from_date: str, to_date: str) -> str:
        """
        Update an employee's title record by closing out the current
        title row and inserting a new title row.
    
        Args:
            employee_id (int): Employee ID.
            title (str): New job title.
            from_date (str): Start date of the new title record.
            to_date (str): End date of the new title record.
    
        Returns:
            str: Confirmation message after update.
        """
        self.logger.info(f"Updating title for employee {employee_id} to {title}")
    
        # Close out the current title row (set its to_date to new from_date)
        sql_query_close = """
            UPDATE employees.title
            SET    to_date = %(from_date)s
            WHERE  employee_id = %(employee_id)s
              AND  from_date = (
                       SELECT MAX(from_date)
                       FROM   employees.title
                       WHERE  employee_id = %(employee_id)s
                   )
        """
    
        # Insert the new title row
        sql_query_insert = """
            INSERT INTO employees.title (employee_id, title, from_date, to_date)
            VALUES (%(employee_id)s, %(title)s, %(from_date)s, %(to_date)s)
        """
    
        sql_parms = {
            "title": title,
            "from_date": from_date,
            "to_date": to_date,
            "employee_id": employee_id
        }
    
        # Execute close query
        self.db_cursor.db_execute(sql_query_close, sql_parms)
        if self.db_cursor.rowcount == 0:
            self.logger.warning(
                f"No existing title row found to close for employee {employee_id}; "
                f"proceeding to insert new row anyway"
            )
    
        # Execute insert query
        self.db_cursor.db_execute(sql_query_insert, sql_parms)
        if self.db_cursor.rowcount != 1:
            self.logger.error(
                f"Expected 1 row inserted for employee {employee_id}, "
                f"got {self.db_cursor.rowcount}"
            )
    
        # Commit transaction
        self.db_cursor.db_commit()
    
        self.logger.info(f"Title update committed for employee {employee_id}")
        return f"Updated title for employee {employee_id} to {title}"