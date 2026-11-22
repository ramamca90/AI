from notification_service.config import get_settings
from notification_service.models import Base
from orderflow_common.migrations import run_alembic_migrations

run_alembic_migrations(Base.metadata, get_settings().database_url, lock_id=72_003)
