"业务只使用 Storage、工作单元及普通记录，映射与 Repository 为包内实现"

from src.storage.errors import StorageConnectionError, StorageConstraintError, StorageError, StorageWriteError
from src.storage.ids import new_id
from src.storage.service import Storage, get_storage, get_storage_factory

initialize_storage = get_storage().initialize
get_pool_status = get_storage().pool_status
close_storage = get_storage().close

__all__ = [
    "Storage",
    "get_storage",
    "get_storage_factory",
    "new_id",
    "initialize_storage",
    "get_pool_status",
    "close_storage",
    "StorageError",
    "StorageConstraintError",
    "StorageConnectionError",
    "StorageWriteError",
]
