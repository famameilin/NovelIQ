"主键及其 UUID 外键使用同一 UUIDv7 存储合同"

from uuid import UUID

from sqlalchemy import Uuid
from sqlalchemy.types import TypeDecorator


class Uuid7(TypeDecorator):
    "写入和按身份查询时拒绝 UUID4/UUID5 或任意文本身份"

    cache_ok = True
    impl = Uuid

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        identifier = UUID(str(value))
        if identifier.version != 7:
            raise ValueError("数据库身份必须由 Storage 分配为 UUIDv7")
        return str(identifier)
