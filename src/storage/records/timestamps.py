"普通记录使用的 UTC 时间格式"

from datetime import UTC, datetime


def naive_utcnow() -> datetime:
    "数据库合同采用不带时区的 UTC 时间"
    return datetime.now(UTC).replace(tzinfo=None)
