from orderflow_common.migrations import run_alembic_migrations
from orders_service.config import get_settings
from orders_service.models import Base

run_alembic_migrations(Base.metadata, get_settings().database_url, lock_id=72_002)
