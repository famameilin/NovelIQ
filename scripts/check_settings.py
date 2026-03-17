from src.config.settings import settings
from dotenv import load_dotenv
from pathlib import Path
import os

# Manually load .env to compare
env_path = Path(__file__).parent.parent / ".env"
load_dotenv(env_path)

print(f"Env ANNOTATION_BASE_URL: {os.getenv('ANNOTATION_BASE_URL')}")
print(f"Settings ANNOTATION_BASE_URL: {settings.models.annotation.base_url}")
print(f"Settings ANNOTATION_MODEL: {settings.models.annotation.model}")
