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
  gen_ai_app.cfg          # Config file (DB connection + log path)
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
log_path = E:\\__playground__\\python\\gen_ai_app\\logs

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
    "command": "C:\\Users\\90ram\\anaconda3\\envs\\gen_ai_app\\python.exe",
    "args": ["E:\\__playground__\\python\\gen_ai_app\\src\\main.py"],
    "transport": "streamable-http"
  }
}
```

**Notes:**
- `command` → Path to your Python interpreter (in your Anaconda environment)
- `args` → Path to your MCP server entry point (`main.py`)
- `transport` → Must be `"streamable-http"` for Claude Desktop MCP integration

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
