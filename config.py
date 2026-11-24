"""Settings, all from the environment (or a .env file read by start.bat / docker compose)."""
import os

DATA_DIR = os.environ.get("INTERNSHIPS_DATA_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "data"))
DB_PATH = os.path.join(DATA_DIR, "internships.db")

HOST = os.environ.get("INTERNSHIPS_HOST", "0.0.0.0")
PORT = int(os.environ.get("INTERNSHIPS_PORT", "8700"))

# How often the background worker checks every source (also settable on the page).
REFRESH_MINUTES = max(5, int(os.environ.get("INTERNSHIP_REFRESH_MINUTES", "30")))
# "off" serves the page without the worker (for a second copy, or tests).
WORKER = os.environ.get("INTERNSHIPS_WORKER", "on").lower() not in ("off", "0", "false", "no")
# Seconds after start before the first check, so the page is answering first.
FIRST_CHECK_DELAY = int(os.environ.get("INTERNSHIPS_FIRST_CHECK_DELAY", "15"))

# The address people open the app at, for links in emails and messages.
PUBLIC_URL = os.environ.get("INTERNSHIPS_PUBLIC_URL", "").rstrip("/")

TIMEOUT = 30
