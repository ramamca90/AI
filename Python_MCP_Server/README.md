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

Update `src/employee_manager.cfg` with your PostgreSQL connection details:

```ini
[employee_manager]
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
    "args": ["E:\\__playground__\\AI\\mcp_server\\src\\main.py"]
  }
}
```

**Notes:**
- `command` → Path to your Python interpreter (in your Anaconda environment)
- `args` → Path to your MCP server entry point (`main.py`)

---

## 📸 Screenshots & Usage Guide

### 1. PostgreSQL Database Schema in pgAdmin 4
<img width="940" height="689" alt="PostgreSQL Database Schema" src="https://github.com/user-attachments/assets/d5e3b477-21e5-4834-bb76-a82af398f705" />

The **employees** schema contains multiple tables for managing employee data:
- **employee**: Stores employee information (ID, first name, last name, gender, hire date)
- **salary**: Maintains salary records with date ranges (employee_id, amount, from_date, to_date)
- **title**: Tracks job titles over time (employee_id, title, from_date, to_date)

This screenshot shows a sample query retrieving employee details and title history for employee ID 100001.

---

### 2. Claude Desktop MCP Configuration File
<img width="1162" height="987" alt="image" src="https://github.com/user-attachments/assets/17a26cec-b6ba-458b-b358-0977884cc3b0" />

The `claude_desktop_config.json` file contains the MCP server registration with:
- **Command**: Path to your Python interpreter in your Anaconda environment
- **Arguments**: Path to the `main.py` entry point

This configuration allows Claude Desktop to automatically start and communicate with the EmployeeManager MCP server.

---

### 3. Claude Desktop - Local MCP Servers Settings
<img width="1026" height="760" alt="image" src="https://github.com/user-attachments/assets/5c5413b6-0b79-4bc4-943d-db49b3fa9ebd" />

The **Local MCP servers** settings panel in Claude Desktop displays:
- **EmployeeManager**: The registered MCP server (marked as "Running")
- **Command**: Path to the Python executable and main.py script
- **Arguments**: Configuration details for the MCP server startup
- **View Logs**: Quick access to troubleshoot any server issues

This panel confirms that the MCP server is properly registered and running.

---

### 4. MCP Server Logs and Execution
<img width="939" height="481" alt="MCP Server Logs" src="https://github.com/user-attachments/assets/2a20aa45-3738-4e87-8966-f7fef8a70c15" />

The console output displays real-time logs from the running MCP server, showing:
- **Server startup**: Successful connection and initialization
- **Processing requests**: Tool calls being processed by the MCP server
- **Query execution**: SQL queries being executed with their parameters
- **Response handling**: Results being returned to Claude Desktop

This log output is essential for debugging and monitoring the server's performance.

---

### 5. Claude Desktop - Chatbot Interface with EmployeeManager Integration
<img width="940" height="567" alt="image" src="https://github.com/user-attachments/assets/2d1c2a8e-3569-45ad-bd43-6b1645f93cd6" />

The main Claude Desktop chat interface showing how the EmployeeManager MCP server is integrated as a connector, providing various tools for employee data queries and management through an intuitive conversational interface. The interface displays the available tools and options for interacting with the MCP server.

---

### 6. Claude Desktop - Connectors and Tool Management
<img width="940" height="394" alt="image" src="https://github.com/user-attachments/assets/0aadd986-1d58-4731-9061-8842cedf5bca" />

The Connectors panel displaying the EmployeeManager integration with all available tools including:
- `get_employee` - Retrieve employee details
- `get_employee_by_partial_name` - Search employees by name
- `get_salary_history` - View salary records
- `update_salary` - Update employee salary
- `get_titles` - Retrieve title history
- `update_title` - Update employee title

Each tool shows its permissions and can be individually managed through this interface.

---

### 7. Claude Desktop - Tool Search and Execution
<img width="940" height="676" alt="image" src="https://github.com/user-attachments/assets/127197ea-7724-4c7f-a52e-7215b1bafa45" />

The tool search and execution functionality showing the process of finding and loading available EmployeeManager tools. This demonstrates how Claude Desktop dynamically searches for relevant tools when a user requests employee data (e.g., "get me employee 100 data") and loads the appropriate tools before executing the query. The interface shows the query request, available tools, and the tool loading process.

---

### 8. Claude Desktop - Query Results and Data Display
<img width="940" height="949" alt="image" src="https://github.com/user-attachments/assets/fa739a3b-674d-4330-8758-a1adce52d568" />

The chat interface displaying successful query results:
- **Employee Information**: Name, gender, and hire date for the requested employee (e.g., employee 10001: Georgi Facello)
- **Salary History**: A comprehensive table showing salary records over time with From/To dates and salary amounts
- **Interactive Display**: Results are displayed in an organized format within Claude Desktop

This demonstrates the complete workflow from query to result display within Claude Desktop, showing how the EmployeeManager MCP server successfully retrieves and presents employee data.

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
