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
# Password required to record payments / settled up / add charge / mark not paid up (ledger actions)
PAYMENT_PASSWORD = os.getenv("PAYMENT_PASSWORD", "Snoopy&Me1216")

# OpenAI (optional): for extracting game data from screenshots
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

# Paths
BASE_DIR = Path(__file__).resolve().parent
UPLOADS_DIR = BASE_DIR / "uploads"
UPLOADS_DIR.mkdir(exist_ok=True)

# Balance tolerance
BALANCE_EPSILON = 0.01

# Common aliases for player matching when the LLM extracts game data (raw_name -> canonical name).
# Used to suggest a player from the database; if the LLM can't match, it leaves the row unassigned but keeps raw_name as a starting point.
PLAYER_ALIASES = {
    "nik": "Nick Pham",
    "AG": "Arjun Garg",
    "Arjun M": "Arjun Mohan",
    "ty": "Tyler Tsay",
}

# Max size per uploaded file (screenshots / player photos); ~10 MB, a bit above typical screenshot size
MAX_UPLOAD_SIZE_BYTES = 10 * 1024 * 1024
MAX_UPLOAD_FILES = int(os.getenv("MAX_UPLOAD_FILES", "6"))

# Keep AI extraction bounded so uploads do not overwhelm the web worker.
MAX_EXTRACT_IMAGE_COUNT = int(os.getenv("MAX_EXTRACT_IMAGE_COUNT", "4"))
MAX_EXTRACT_IMAGE_BYTES = int(os.getenv("MAX_EXTRACT_IMAGE_BYTES", str(6 * 1024 * 1024)))
MAX_EXTRACT_TOTAL_BYTES = int(os.getenv("MAX_EXTRACT_TOTAL_BYTES", str(20 * 1024 * 1024)))
OPENAI_REQUEST_TIMEOUT_SECONDS = int(os.getenv("OPENAI_REQUEST_TIMEOUT_SECONDS", "45"))
