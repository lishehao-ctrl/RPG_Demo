import uuid

from sqlalchemy import JSON, String, TypeDecorator
from sqlalchemy.dialects.postgresql import JSONB


class GUID(TypeDecorator):
    """Cross-dialect UUID storage.

    - PostgreSQL: native UUID
    - Others (e.g. SQLite): CHAR(36)
    """

    impl = String(36)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return value
        if isinstance(value, uuid.UUID):
            return str(value)
        return str(uuid.UUID(value))

    def process_result_value(self, value, dialect):
        if value is None:
            return value
        return uuid.UUID(str(value))


JSONType = JSON().with_variant(JSONB(), "postgresql")
