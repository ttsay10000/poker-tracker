"""App configuration from environment.

Env document (set in .env or environment):

  DATABASE_URL       Optional. Postgres URL; if unset, uses SQLite at BASE_DIR/poker.db.
  ADMIN_PASSWORD     Required. Password for protected routes.
  SECRET_KEY         Optional. Session/signing secret; defaults to ADMIN_PASSWORD.
  OPENAI_API_KEY     Optional. For extracting game data from screenshots/notes (Add game).
"""
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

# OpenAI (optional): for extracting game data from screenshots
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

# Paths
BASE_DIR = Path(__file__).resolve().parent
UPLOADS_DIR = BASE_DIR / "uploads"
UPLOADS_DIR.mkdir(exist_ok=True)

# Balance tolerance
BALANCE_EPSILON = 0.01
