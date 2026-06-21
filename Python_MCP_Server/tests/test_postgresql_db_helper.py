from unittest.mock import MagicMock, patch
from src.postgresql_db_helper import PostgreSQLDBConnection, PostgreSQLDBCursor

@patch("src.postgresql_db_helper.psycopg.connect")
def test_connection_established(mock_connect):
    mock_connect.return_value = MagicMock()
    conn = PostgreSQLDBConnection()
    assert conn.status is True

def test_cursor_execute_and_fetch(monkeypatch):
    fake_cursor = MagicMock()
    fake_cursor.fetchall.return_value = [("row1",)]
    conn = MagicMock()
    conn.connection.cursor.return_value = fake_cursor
    cursor = PostgreSQLDBCursor(conn)
    cursor.db_execute("SELECT 1")
    rows = cursor.db_fetch_all()
    assert rows == [("row1",)]
