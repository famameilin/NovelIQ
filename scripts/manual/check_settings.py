import os
import sys
from pathlib import Path

from dotenv import load_dotenv

project_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(project_root))

from src.config.settings import settings

# Manually load .env to compare
env_path = project_root / ".env"
load_dotenv(env_path)

print(f"Env ANNOTATION_BASE_URL: {os.getenv('ANNOTATION_BASE_URL')}")
print(f"Settings ANNOTATION_BASE_URL: {settings.models.annotation.base_url}")
print(f"Settings ANNOTATION_MODEL: {settings.models.annotation.model}")
