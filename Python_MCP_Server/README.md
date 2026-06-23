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

## 📸 Screenshots & Usage Guide

### 1. Claude Desktop - Chatbot Interface with EmployeeManager Integration
![Claude Desktop Chatbot Interface](https://github.com/ramamca90/AI/assets/screenshot1.png)

The main Claude Desktop chat interface showing how the EmployeeManager MCP server is integrated as a connector, providing various tools for employee data queries and management through an intuitive conversational interface.

---

### 2. Claude Desktop - Connectors and Tool Management
![Claude Desktop Connectors Settings](https://github.com/ramamca90/AI/assets/screenshot2.png)

The Connectors panel displaying the EmployeeManager integration with all available tools including:
- `get_employee` - Retrieve employee details
- `get_employee_by_partial_name` - Search employees by name
- `get_salary_history` - View salary records
- `update_salary` - Update employee salary
- `get_titles` - Retrieve title history
- `update_title` - Update employee title

Each tool shows its permissions and can be individually managed.

---

### 3. Claude Desktop - Tool Search and Execution
![Tool Search Results](https://github.com/ramamca90/AI/assets/screenshot3.png)

The tool search functionality showing the process of finding and loading available EmployeeManager tools. This demonstrates how Claude Desktop dynamically searches for relevant tools when a user requests employee data (e.g., "get me employee 100 data") and loads the appropriate tools before executing the query.

---

### 4. Claude Desktop - Query Results and Data Display
![Query Results with Employee Data](https://github.com/ramamca90/AI/assets/screenshot4.png)

The chat interface displaying successful query results:
- **Employee Information**: Name, gender, and hire date for the requested employee (e.g., employee 10001: Georgi Facello)
- **Salary History**: A table showing salary records over time with From/To dates and salary amounts
- This demonstrates the complete workflow from query to result display within Claude Desktop

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
