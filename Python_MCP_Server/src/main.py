from employee_db import EmployeeDB
from mcp.server.fastmcp import FastMCP


# --- MCP Server Setup ---
mcp = FastMCP("EmployeeManager")
db = EmployeeDB()
#Connect postgreSQL database
db.connect_database()

@mcp.tool()
def get_employee_by_partial_name(name_pattern: str) -> str:
    """
    MCP tool wrapper for get_employee_by_partial_name.
    Retrieves employees whose first or last name matches the given pattern.
    """
    return db.get_employee_by_partial_name(name_pattern)

@mcp.tool()
def get_employee(employee_id: int) -> str:
    """MCP tool wrapper for get_employee."""
    return db.get_employee(employee_id)

@mcp.tool()
def get_salary_history(employee_id: int) -> str:
    """MCP tool wrapper for get_salary_history."""
    return db.get_salary_history(employee_id)

@mcp.tool()
def update_employee_name(employee_id: int, first_name: str, last_name: str) -> str:
    """MCP tool wrapper for update_employee_name."""
    return db.update_employee_name(employee_id, first_name, last_name)

@mcp.tool()
def update_salary(employee_id: int, amount: int, from_date: str, to_date: str) -> str:
    """MCP tool wrapper for update_salary."""
    return db.update_salary(employee_id, amount, from_date, to_date)

@mcp.tool()
def get_titles(employee_id: int) -> str:
    """
    MCP tool wrapper for get_titles.
    Retrieves all titles/roles for the given employee.
    """
    return db.get_titles(employee_id)

@mcp.tool()
def update_title(employee_id: int, title: str, from_date: str, to_date: str) -> str:
    """
    MCP tool wrapper for update_title.
    Closes out the current title record and inserts a new one
    with the latest role and date range.
    """
    return db.update_title(employee_id, title, from_date, to_date)

if __name__ == "__main__":
    db.logger.info("Starting EmployeeManager MCP server...")
    mcp.run()
