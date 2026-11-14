import asyncio
import os
import threading
import time

from flask import Flask

import bot

app = Flask(__name__)

_running = True
_RETRY_DELAY = 5


def _run_bot_forever():
    """Запускает поллер бота с авто-перезапуском при любых сбоях."""
    while _running:
        try:
            asyncio.run(bot.main())
        except Exception as exc:  # noqa: BLE001
            print(f"[bot] poller stopped with {type(exc).__name__}: {exc}; retry in {_RETRY_DELAY}s")
        time.sleep(_RETRY_DELAY)


@app.route("/")
def index():
    return "NFT offer bot is running"


@app.route("/healthz")
def healthz():
    return "ok"


# Стартуем поллер на уровне модуля: срабатывает и под gunicorn (app:app),
# и под python app.py. gunicorn НЕ выполняет if __name__ == "__main__",
# поэтому поток поднимаем здесь, при импорте.
_bot_thread = threading.Thread(target=_run_bot_forever, daemon=True)
_bot_thread.start()

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    app.run(host="0.0.0.0", port=port)