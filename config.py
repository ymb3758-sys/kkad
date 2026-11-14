import os

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    pass

BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
_admin: str = os.getenv("ADMIN_IDS", "")
if not _admin:
    raise SystemExit("ADMIN_IDS не задан. Укажи в .env или в переменных хостинга.")
ADMIN_IDS: list[int] = [
    int(x.strip()) for x in _admin.split(",") if x.strip()
]
_log = os.getenv("ADMIN_LOG_CHAT_ID", "")
ADMIN_LOG_CHAT_ID: int | None = int(_log) if _log else None
GUARANTOR_ID: str = os.getenv("GUARANTOR_ID", "8090009094")
GUARANTOR_LABEL: str = os.getenv("GUARANTOR_LABEL", "8090009094")
DATABASE_PATH: str = os.getenv("DATABASE_PATH", "offers.db")