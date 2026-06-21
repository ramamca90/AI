import pytest
from src.employee_db import EmployeeDB

# Fake datasets
FAKE_EMPLOYEES = [
    (1, "John", "Doe", "M", "2020-01-01"),
    (2, "Jane", "Smith", "F", "2019-05-05"),
]

FAKE_SALARIES = {
    1: [(50000, "2020-01-01", "2021-01-01"), (60000, "2021-01-02", "2022-01-01")],
    2: [(55000, "2019-05-05", "2020-05-05")],
}

FAKE_TITLES = {
    1: [("Engineer", "2020-01-01", "2021-01-01"), ("Senior Engineer", "2021-01-02", "2022-01-01")],
    2: [("Analyst", "2019-05-05", "2020-05-05")],
}


class FakeCursor:
    """Fake cursor that mimics db_execute, db_fetch_one, db_fetch_all, db_commit."""

    def __init__(self):
        self.rowcount = 0
        self._last_query = None
        self._last_params = None
        self.db_execute_call_count = 0

    def db_execute(self, query, params=None):
        self._last_query = query
        self._last_params = params or {}
        self.db_execute_call_count += 1
        if query.strip().upper().startswith(("UPDATE", "INSERT")):
            self.rowcount = 1
        else:
            self.rowcount = 0

    def db_fetch_one(self):
        emp_id = self._last_params.get("employee_id")
        for e in FAKE_EMPLOYEES:
            if e[0] == emp_id:
                return e[1], e[2], e[3], e[4]
        return None

    def db_fetch_all(self):
        if "salary" in self._last_query:
            return FAKE_SALARIES.get(self._last_params.get("employee_id"), [])
        elif "title" in self._last_query:
            return FAKE_TITLES.get(self._last_params.get("employee_id"), [])
        elif "employee" in self._last_query:
            pattern = self._last_params.get("pattern", "").strip("%").lower()
            return [e for e in FAKE_EMPLOYEES if pattern in e[1].lower() or pattern in e[2].lower()]
        return []

    def db_commit(self):
        return True


@pytest.fixture
def fake_db():
    """Fixture that returns EmployeeDB with FakeCursor injected."""
    db = EmployeeDB()
    db.db_cursor = FakeCursor()
    return db
