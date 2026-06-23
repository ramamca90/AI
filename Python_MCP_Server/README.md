# EmployeeManager MCP Server

EmployeeManager is a **Model Context Protocol (MCP) server** built in Python to manage employee data (names, salaries, titles/roles) with PostgreSQL.  
It integrates seamlessly with **Claude Desktop** so you can query and update employee records directly through Claude's MCP tools.

---

## 🚀 Features

- **Employee Lookup**
  - Get employee details by ID
  - Search employees by partial name
- **Salary Management**
  - Retrieve salary history
  - Update salary (close old record, insert new record)
- **Title/Role Management**
  - Retrieve title history
  - Update title (close old record, insert new record)
- **Employee Updates**
  - Update employee name

All operations are logged using a rotating file logger (`logger_helper.py`).

---

## 🛠️ Project Structure

```
src/
  employee_db.py          # PostgreSQL operations for employees schema
  employee_manager.cfg    # Config file (DB connection + log path)
  logger_helper.py        # Logging helper
  main.py                 # MCP server setup + tool wrappers
  postgresql_db_helper.py # PostgreSQL connection/cursor helper

tests/
  conftest.py             # Shared fixtures (FakeCursor + fake dataset)
  test_employee_db.py     # Unit tests for EmployeeDB methods
  test_logger_helper.py   # Unit tests for logger helper
  test_main.py            # Unit tests for MCP tool wrappers
  test_postgresql_db_helper.py # Unit tests for DB helper
```

---

## ⚙️ Setup

### 1. Install dependencies

```bash
pip install MCP psycopg pytest
```

### 2. Configure database

Update `src/gen_ai_app.cfg` with your PostgreSQL connection details:

```ini
[gen_ai_app]
log_path = E:\\__playground__\\AI\\mcp_server\\logs

[postgresql]
host = localhost
port = 5432
database = MyDatabase01
user = postgres
password = root
```

### 3. Run MCP server

```bash
python src/main.py
```

---

## 🔗 Claude Desktop Integration

Configure Claude Desktop to run your MCP server directly from your local environment.
Update your `claude_desktop_config.json` file with the following entry:

```json
"mcpServers": {
  "EmployeeManager": {
    "command": "C:\\Users\\90ram\\anaconda3\\envs\\mcp_server\\python.exe",
    "args": ["E:\\__playground__\\AI\\mcp_server\\src\\main.py"],
    "transport": "streamable-http"
  }
}
```

**Notes:**
- `command` → Path to your Python interpreter (in your Anaconda environment)
- `args` → Path to your MCP server entry point (`main.py`)
- `transport` → Must be `"streamable-http"` for Claude Desktop MCP integration

---

## 📸 Screenshots

### 1. PostgreSQL Database Schema in pgAdmin 4
![pgAdmin 4 - Employee Database](https://github.com/ramamca90/AI/assets/database-schema.png)

The **employees** schema contains multiple tables for managing employee data:
- **employee**: Stores employee information (ID, first name, last name, gender, hire date)
- **salary**: Maintains salary records with date ranges (employee_id, amount, from_date, to_date)
- **title**: Tracks job titles over time (employee_id, title, from_date, to_date)

This screenshot shows a sample query retrieving employee details and title history for employee ID 100001.

---

### 2. Claude Desktop MCP Configuration
![Claude Desktop Config - MCP Server Setup](https://github.com/ramamca90/AI/assets/claude-config.png)

The `claude_desktop_config.json` file contains the MCP server registration with:
- **Command**: Path to your Python interpreter in your Anaconda environment
- **Arguments**: Path to the `main.py` entry point
- **Transport**: Set to `streamable-http` for Claude Desktop integration

This configuration allows Claude Desktop to automatically start and communicate with the EmployeeManager MCP server.

---

### 3. Claude Desktop - Local MCP Servers Settings
![Claude Desktop Settings - Local MCP Servers](https://github.com/ramamca90/AI/assets/claude-mcp-settings.png)

The **Local MCP servers** settings panel in Claude Desktop displays:
- **EmployeeManager**: The registered MCP server (marked as "Running")
- **Command**: Path to the Python executable and main.py script
- **Arguments**: Configuration details for the MCP server startup
- **View Logs**: Quick access to troubleshoot any server issues

This panel confirms that the MCP server is properly registered and running.

---

### 4. MCP Server Logs and Execution
![MCP Server Output - Logs and Processing](https://github.com/ramamca90/AI/assets/mcp-server-logs.png)

The console output displays real-time logs from the running MCP server, showing:
- **Server startup**: Successful connection and initialization
- **Processing requests**: Tool calls being processed by the MCP server
- **Query execution**: SQL queries being executed with their parameters
- **Response handling**: Results being returned to Claude Desktop

This log output is essential for debugging and monitoring the server's performance.

---

## 📋 Logs

If any exceptions occur while running the MCP server, Claude Desktop will log them in:

```
mcp-server-EmployeeManager.log
```

This log file is located in Claude Desktop's logs directory and is useful for debugging issues with your MCP server.

---

## 🧪 Running Tests

Run all unit tests with:

```bash
pytest -v
```
