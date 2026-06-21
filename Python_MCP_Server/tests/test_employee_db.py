def test_get_employee_found(fake_db):
    result = fake_db.get_employee(1)
    assert "John Doe" in result

def test_get_employee_not_found(fake_db):
    result = fake_db.get_employee(999)
    assert result == "Employee not found"

def test_get_employee_by_partial_name_found(fake_db):
    result = fake_db.get_employee_by_partial_name("Jane")
    assert "Jane Smith" in result

def test_get_employee_by_partial_name_no_matches(fake_db):
    result = fake_db.get_employee_by_partial_name("XYZ")
    assert result == "No employees found"

def test_get_salary_history_found(fake_db):
    result = fake_db.get_salary_history(1)
    assert "50000 from 2020-01-01 to 2021-01-01" in result
    assert "60000 from 2021-01-02 to 2022-01-01" in result

def test_get_salary_history_no_records(fake_db):
    result = fake_db.get_salary_history(999)
    assert result == "No salary records"

def test_get_titles_found(fake_db):
    result = fake_db.get_titles(1)
    assert "Engineer" in result
    assert "Senior Engineer" in result

def test_get_titles_no_records(fake_db):
    result = fake_db.get_titles(999)
    assert result == "No titles found"

def test_update_employee_name(fake_db):
    result = fake_db.update_employee_name(1, "Alice", "Wonderland")
    assert "Updated employee 1 name to Alice Wonderland" in result

def test_update_salary_success(fake_db):
    fake_db.db_cursor.rowcount = 1
    result = fake_db.update_salary(1, 70000, "2022-01-02", "2023-01-01")
    assert "Updated salary for employee 1 to 70000" in result

def test_update_salary_no_existing_row(fake_db, caplog):
    fake_db.db_cursor.rowcount = 0
    result = fake_db.update_salary(1, 80000, "2023-01-02", "2024-01-01")
    assert "Updated salary for employee 1 to 80000" in result
    warnings = [rec.message for rec in caplog.records if rec.levelname == "WARNING"]
    assert any("No existing salary row found to close" in msg for msg in warnings)

def test_update_title_success(fake_db):
    fake_db.db_cursor.rowcount = 1
    result = fake_db.update_title(1, "Manager", "2022-01-02", "2023-01-01")
    assert "Updated title for employee 1 to Manager" in result
    assert fake_db.db_cursor.db_execute_call_count == 2

def test_update_title_no_existing_row(fake_db, caplog):
    fake_db.db_cursor.rowcount = 0
    result = fake_db.update_title(1, "Director", "2023-01-02", "2024-01-01")
    assert "Updated title for employee 1 to Director" in result
    warnings = [rec.message for rec in caplog.records if rec.levelname == "WARNING"]
    assert any("No existing title row found to close" in msg for msg in warnings)
