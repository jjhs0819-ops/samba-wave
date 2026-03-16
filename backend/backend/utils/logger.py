import logging
import sys

# ─────────────────────────────────────────────────────────────
# 0) List of logger names to silence
SILENCE_LOGGERS = ("httpx", "httpcore", "fal_client")

# 1) Initialize root logger
for h in logging.root.handlers[:]:
    logging.root.removeHandler(h)

fmt = logging.Formatter("%(levelname)s - %(message)s")
console = logging.StreamHandler(sys.stdout)
console.setFormatter(fmt)

logger = logging.getLogger()
logger.setLevel(logging.INFO)
logger.addHandler(console)

# 1-A) Raise specific logger levels to WARNING or higher
for name in SILENCE_LOGGERS:
    logging.getLogger(name).setLevel(logging.WARNING)


# (Optional) Filter based on message content:
class DropFalPolling(logging.Filter):
    """Drop httpx logs containing 'queue.fal.run'"""

    def filter(self, record: logging.LogRecord) -> bool:
        if record.name in SILENCE_LOGGERS and "queue.fal.run" in record.getMessage():
            return False
        return True


logger.addFilter(DropFalPolling())
