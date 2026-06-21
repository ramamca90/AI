import pytest
from unittest.mock import MagicMock
import src.main as main

@pytest.fixture(autouse=True)
def mock_db(monkeypatch):
    fake_db = MagicMock()
    fake_db.get_employee.return_value = "John Doe"
    fake_db.get_salary_history.return_value = "Salary history"
    fake_db.get_titles.return_value = "Engineer"
    fake_db.update_title.return_value = "Updated title"
    fake_db.update_salary.return_value = "Updated salary"
    fake_db.update_employee_name.return_value = "Updated name"
    fake_db.get_employee_by_partial_name.return_value = "Partial match"
    main.db = fake_db
    return fake_db

def test_get_employee_tool():
    assert main.get_employee(1) == "John Doe"

def test_get_salary_history_tool():
    assert main.get_salary_history(1) == "Salary history"

def test_get_titles_tool():
    assert main.get_titles(1) == "Engineer"

def test_update_title_tool():
    assert main.update_title(1, "Manager", "2022-01-02", "2023-01-01") == "Updated title"

def test_update_salary_tool():
    assert main.update_salary(1, 70000, "2022-01-02", "2023-01-01") == "Updated salary"

def test_update_employee_name_tool():
    assert main.update_employee_name(1, "Alice", "Wonderland") == "Updated name"

def test_get_employee_by_partial_name_tool():
    assert main.get_employee_by_partial_name("Jo") == "Partial match"
