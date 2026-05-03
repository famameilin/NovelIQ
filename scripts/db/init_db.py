import sys
from pathlib import Path

from dotenv import load_dotenv

project_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(project_root))

from src.storage.database_url import resolve_database_url_from_env  # noqa: E402
from src.storage.db import init_db  # noqa: E402

# 从项目根目录加载 .env
env_path = project_root / ".env"
load_dotenv(env_path)

print(f"Initializing database using: {resolve_database_url_from_env('DATABASE_URL')}")
init_db(include_level3_tables=True)
print("Database initialized.")
