from __future__ import annotations

import signal
import time
from threading import Event

from config import load_config
from logger import setup_logger
from wifi_monitor import WifiMonitor


def main() -> None:
    config = load_config()
    logger = setup_logger()
    stop_event = Event()

    def handle_shutdown(signum: int, _frame: object) -> None:
        logger.info("Shutdown signal received: %s", signum)
        stop_event.set()

    signal.signal(signal.SIGINT, handle_shutdown)
    signal.signal(signal.SIGTERM, handle_shutdown)

    monitor = WifiMonitor(config=config, logger=logger)
    logger.info("Program started")

    try:
        while not stop_event.is_set():
            try:
                monitor.check_and_reconnect()
            except Exception:
                logger.exception("Unexpected exception during monitor loop")

            stop_event.wait(config.check_interval)
    finally:
        logger.info("Program stopped")
        time.sleep(0.1)


if __name__ == "__main__":
    main()
