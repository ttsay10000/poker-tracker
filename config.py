"""App configuration from environment."""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Database
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    # SQLite for local dev
    BASE_DIR = Path(__file__).resolve().parent
    DATABASE_URL = f"sqlite:///{BASE_DIR / 'poker.db'}"

# Render uses postgres:// but SQLAlchemy expects postgresql://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# Auth
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")
SECRET_KEY = os.getenv("SECRET_KEY", ADMIN_PASSWORD or "dev-secret")

# Paths
BASE_DIR = Path(__file__).resolve().parent
UPLOADS_DIR = BASE_DIR / "uploads"
UPLOADS_DIR.mkdir(exist_ok=True)

# Balance tolerance
BALANCE_EPSILON = 0.01
