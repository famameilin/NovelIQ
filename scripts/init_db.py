from src.storage.db import init_db
from dotenv import load_dotenv
import os
from pathlib import Path

# Load env from root
env_path = Path(__file__).parent.parent / ".env"
load_dotenv(env_path)

print(f"Initializing database using: {os.getenv('DATABASE_URL')}")
init_db()
print("Database initialized.")
