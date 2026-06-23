
"""
    Module to connect and interact with PostgreSQL Database using psycopg package.
    The PostgreSQLDBConnection, PostgreSQLDBCursor, PostgreSQLDatabaseHelper follow practices defined in the PEP 249 Python DB API specification

    Usage:
        import postgresql_db_helper.py module into other python modules
    
        from postgresql_db_helper import PostgreSQLDatabaseHelper


    # Example usage
    
    # TEST1: Running a SELECT query
    db = PostgreSQLDatabaseHelper(logger)
    sql_query = \"""
        SELECT
            RLL_ID, RLL_CRTDBY, RLL_MOBBY, RLL_CRTDT, RLL_MODDT, US_UID
        FROM ABCD
        WHERE RLL_CRTDBY = :roll
    \"""
    args = {'roll': 'amara'}
    
    cursor_instance = db.connect().create_cursor_instance()
    cursor_instance.db_execute(sql_query, args)
    rows = cursor_instance.db_fetch_all()
    print(rows)
    db.disconnect_database()
    
    # TEST2: Running an INSERT query
    db = PostgreSQLDatabaseHelper(logger)
    insert_query = \"""
        insert into abcd(RLL_ID, RLL_CRTDBY, RLL_MOBBY, RLL_CRTDT, RLL_MODDT, US_UID)
        values(:1, :2, :3, to_date('2024/02/07', 'yyyy/mm/dd'),
               to_date('2024/02/07', 'yyyy/mm/dd'), :4)
    \"""
    args = {'roll': 'amara'}
    
    cursor_instance = db.connect().create_cursor_instance()
    # TEST3: Insert multiple records
    db = PostgreSQLDatabaseHelper(logger)
    insert_query = \"""
        insert into abcd(RL_ID, RLL_CRTDBY, RLL_MODBY, RLL_CRTDOT, RLL_MODDT, US_UID)
        values(:1, :2, :3, to_date('2024/02/07', 'yyyy/mm/dd'),
               to_date('2024/02/07', 'yyyy/mm/dd'), :4)
    \"""
    rows = [
        ('999', 'amara', 'amarar1334', 'amarar23'),
        ('999', 'amara', 'amarar1434', 'amarar24'),
        ('999', 'amara', 'amarar1534', 'amarar25')
    ]
    
    cursor_instance = db.connect().create_cursor_instance()
    cursor_instance.db_execute_many(insert_query, rows)
    affected_rows_count = cursor_instance.rowcount
    print(affected_rows_count)
    cursor_instance.db_commit()
    db.disconnect_database()
    
    
    # Using context manager, no need to open & close connections explicitly
    
    # TEST4: SELECT Query
    with PostgreSQLDatabaseHelper(self.logger) as cursor_instance:
        if cursor_instance.db_execute(sql_query, args):
            rows = cursor_instance.db_fetch_all()
            print(rows)
    
    
    # TEST5: UPDATE/INSERT with single record
    with PostgreSQLDatabaseHelper(self.logger) as cursor_instance:
        cursor_instance.db_execute(sql_query, args)
        affected_rows_count = cursor_instance.rowcount
        print(affected_rows_count)
        cursor_instance.db_commit()
    
    
    # TEST6: UPDATE/INSERT with multiple records
    with PostgreSQLDatabaseHelper(self.logger) as cursor_instance:
        cursor_instance.db_execute_many(sql_query, rows)
        affected_rows_count = cursor_instance.rowcount
        print(affected_rows_count)
        cursor_instance.db_commit()
    cursor_instance.db_commit()
    
    # Instantiated db to be used as a decorator for a function
    
    # TEST7: Using decorator for SELECT
    database_connection = PostgreSQLDatabaseHelper(logger)
    
    @database_connection
    def fun(cursor_instance, f_arg1, f_arg2):
        cursor_instance.db_execute(sql_query, sql_args)
        print(cursor_instance.db_fetch_all())
        print(f_arg1, f_arg2)
    
    fun("arg1_value", "arg2_value")
    
    
    # TEST8: Using decorator for UPDATE/INSERT
    database_connection = PostgreSQLDatabaseHelper(logger)
    
    @database_connection
    def fun(cursor_instance, f_arg1, f_arg2):
        cursor_instance.db_execute(sql_query, sql_args)
        affected_rows_count = cursor_instance.rowcount
        print(affected_rows_count)
        cursor_instance.db_commit()
        print(f_arg1, f_arg2)
    
    fun("arg1_value", "arg2_value")
    
"""

# Imports and setup
from configparser import ConfigParser
import logging
import sys
import psycopg

sys.path.append('/data/cronscripts/support_tools/')

DB_INI_FILE = "E:\\__playground__\\AI\\mcp_server\\src\\employee_manager.cfg"

logger = None

class PostgreSQLDBConnection:
    """
    This class specifies to:
    - Make connection with PostgreSQL database
    - Generate database cursor instance
    """

    def __init__(self):
        """ Initialize all database values """

        self.__connection = None
        self._cursor_instance = None

        self._get_connection_values()
        self._make_connection()


    # Protected methods
    def _get_connection_values(self):
        """ Protected method to collect the PostgreSQL connection values """

        # create a parser
        parser = ConfigParser()
        # read config file
        parser.read(DB_INI_FILE)
    
        # get section, default to postgresql
        db_params = {}

        if parser.has_section('postgresql'):
            params = parser.items('postgresql')
            for param in params:
                db_params[param[0]] = param[1]
        else:
            raise Exception(f"{DB_INI_FILE} file not exists or Section 'postgresql' not found")
        

        self._db_user = db_params['user']
        self.__db_pass = db_params['password']
        self._db_host = db_params['host']
        self._db_database = db_params['database']
        self._db_port = int(db_params['port']) if 'port' in db_params else 5432
        self._db_schema = db_params['schema'] if 'schema' in db_params else 'public'

    
    def _make_connection(self):
        """ Establishing the PostgreSQL connection """
        try:
            self.__connection = psycopg.connect(
                host=self._db_host,
                port=self._db_port,
                dbname=self._db_database,
                user=self._db_user,
                password=self.__db_pass
                #options=f'-c search_path={self._db_schema}'
            )

            #self._connection = psycopg.connect(**self._get_connection_values())
            self.connected = True
            logger.info("Connected to Database")
    
        except psycopg.Error as exc:
            logger.critical(exc)
            raise exc
        
    
    @property
    def connection(self):
        """Get the PostgreSQL connection instance"""
        return self.__connection
    
    @property
    def status(self):
        """Returns the current active status of the PostgreSQL connection"""
        return not self.connection.closed  # checks if the connection is open
    

    def connection_close(self):
        """Close the cursor PostgreSQL statements, the PostgreSQL connection, and reset the reference"""
        if self._cursor_instance:
            self._cursor_instance.cursor_close()
    
        self._cursor_instance = None
    
        if self.connection:
            self.connection.close()
    
        self.__connection = None
        
        logger.info("Disconnected from database")

    
    def create_cursor_instance(self):
        """Create the cursor instance. If one is active, clear it."""
        if self._cursor_instance:
            self._cursor_instance.cursor_close()
            self._cursor_instance = None
    
        self._cursor_instance = PostgreSQLDBCursor(self)
    
        logger.debug("created database cursor")
    
        return self._cursor_instance
    
    
    def __repr__(self):
        msg = (
            f"Connection object [{self.connection}]\n"
            f" DB User [{self._db_user}], DB Host [{self._db_host}]"
            f" DB Database [{self._db_database}], DB Port [{self._db_port}]"
        )
        return msg


class PostgreSQLDBCursor:
    """Emulate cursor behaviors on PostgreSQL DB in accordance with PEP 249"""

    def __init__(self, db_connection_instance):

        self._connection = db_connection_instance
        # Creating cursor for current DB connection
        self.db_cursor = self.connection.cursor()


    @property
    def connection(self):
        """Alias to the parent connection's PostgreSQL connection"""
        return self._connection.connection


    @property
    def db_commit(self):
        """Commit the transactions"""
        return self.connection.commit
    

    @property
    def db_rollback(self):
        """Rollback the transactions"""
        return self.connection.rollback
    
    
    @property
    def rowcount(self):
        """Return affected rows, only used for INSERT, UPDATE, DELETE"""
        if self.db_cursor:
            return self.db_cursor.rowcount
        return 0
    
    
    def db_execute(self, sql, args={}):
        """
        Log the query, prepare it, and execute it
    
        Arguments:
            sql (str) -- SQL string
            args (dict) -- Dict of arguments to pass into the query
                ex - {'en_id': 3640, 'invoice': 23123}
    
        Returns:
            psycopg.Cursor or None , None for UPDATE/INSERT/DELETE etc.
        """
        self.log_query(sql, args)
        if not self.db_cursor:
            return None
    
        return self.db_cursor.execute(sql, args)
    
    
    def db_execute_many(self, sql, rows):
        """
        Insert multiple rows efficiently using Cursor.executemany().
    
        Arguments:
            sql (str) -- SQL string
            rows -- list of tuples
                ex - [('col1_value1', 'col2_value1'),
                      ('col1_value2', 'col2_value2'),
                      ('col1_value3', 'col2_value3')]
    
        Returns:
            Affected row count
        """
        self.log_query(sql, rows)
        if not self.db_cursor:
            return None
    
        self.db_cursor.executemany(sql, rows)
        return self.rowcount
    
    
    def db_fetch_all(self):
        """
        Collect all rows in query result.
    
        Returns:
            List of tuples, each row in tuple format
                ex - [('col1_value1', 'col2_value1'),
                      ('col1_value2', 'col2_value2'),
                      ('col1_value3', 'col2_value3')]
        """
        if not self.db_cursor:
            return []
    
        return self.db_cursor.fetchall()
    
    
    def db_fetch_one(self):
        """
        Fetch single row from current db_cursor
    
        Returns:
            tuple - The single returned PostgreSQL db row
            ex - ('col1_value1', 'col2_value1')
        """
        if not self.db_cursor:
            return []
    
        return self.db_cursor.fetchone()
    
    
    def cursor_close(self):
        """Reset and clear the PostgreSQL Statement instance"""
        if self.db_cursor:
            self.db_cursor.close()
    
    
    def log_query(self, operation, parameters):
        """Logs the SQL and args"""
        logger.debug(f"SQL Operation: [{operation}]")
        logger.debug(f"SQL Parameters: [{parameters}]")
    
    
    def description(self):
        """Return PostgreSQL Database Cursor Description"""
        if not self.db_cursor:
            return None
    
        return self.db_cursor.description


class PostgreSQLDatabaseHelper:
    """
    Helper class to connect to and interact with PostgreSQL database.
    Connects to the database, acts as a context manager, and allows for decoration.
    """

    def __init__(self, _logger):
    
        global logger
        logger = _logger
    
        # logger instance should be required to get secrets from GCP secret manager
        if not isinstance(logger, logging.Logger):
            raise TypeError("logger instance should be required to get secrets from GCP secret manager")
    
        # Counter for context managers
        self.is_open = 0
        self.connection = None
    
    
    @property
    def connected(self):
        """Check the active status of the connection using PostgreSQL DB"""
        return self.connection.status if self.connection else False
    
    
    # Public methods
    def connect(self):
        """Connect to the PostgreSQL DB and return the Connection instance"""
        if self.connected:
            return self.connection
    
        self.connection = PostgreSQLDBConnection()
        return self.connection
    
    
    def disconnect_database(self):
        """Close the session if it's open"""
        if self.connected:
            self.connection.connection_close()
        self.connection = None

    
    # Dunder overrides
    def __enter__(self):
        """
        Handles the opening of the context manager.
        Checks if we are already in a context, connects if not.
    
        Returns:
            {Database}: An open connection that can be reached with Database.cursor
    
        Examples:
            with Database(logger) as cursor:
                cursor.db_execute(sql, args)
        """
        # Increment the context manager requests
        self.is_open += 1
    
        return self.connect().create_cursor_instance()
    
    
    def __exit__(self, exc_type, exc_value, traceback):
        """
        Exits the context manager. If the context was open previously, then
        decrement the requests. When the last request is closing, then close
        the connection.
        """
        # Decrement the context manager requests
        self.is_open -= 1
        # If it's the last request, close it
        if self.is_open == 0:
            self.disconnect_database()
    
    
    def __call__(self, func):
        """
        Allow for instantiated db to be used as a decorator
        """
        def wrapper(*args, **kw):
            # Open the context manager for this function only
            with self as cursor:
                args = (cursor,) + args
                # Here func's first argument will always be the cursor instance
                return func(*args, **kw)
            
        return wrapper
    
    
    def __del__(self):
        """
        It's only important to close and clear the properties
        Then allow for garbage collection to handle the rest. 
        We don't want to force close the connection
        """
        self.disconnect_database()
