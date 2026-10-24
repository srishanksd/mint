import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")
DATA_DIR = Path(os.getenv("MINT_DATA_DIR", BASE_DIR / "data"))
GENERATED_DIR = Path(os.getenv("MINT_GENERATED_DIR", BASE_DIR / "generated"))

DB_PATH = Path(os.getenv("MINT_DB_PATH", DATA_DIR / "mint.db"))

SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "mint-chronoforge-dev-secret-key-2026")
AI_PROVIDER = os.getenv("AI_PROVIDER", "local_heuristic")
AI_API_KEY = os.getenv("AI_API_KEY", "")
AI_MODEL = os.getenv("AI_MODEL", "gemini-3.1-flash-lite")

PORT = int(os.getenv("PORT", 5000))
HOST = os.getenv("HOST", "127.0.0.1")

# Allow OAuth 2.0 token exchange over HTTP for local development (http://127.0.0.1:5000)
os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"


def get_db_path() -> Path:
    return Path(DB_PATH)


def get_generated_dir() -> Path:
    return Path(GENERATED_DIR)
