from __future__ import annotations

import signal
import time
from ctypes import WinDLL, get_last_error, wintypes
from threading import Event

from config import load_config
from logger import setup_logger
from tgate_agent import TgateSmartAgentAutomator
from wifi_monitor import WifiMonitor


ERROR_ALREADY_EXISTS = 183
MUTEX_NAME = "Global\\WifiAutoReconnectAgent"

kernel32 = WinDLL("kernel32", use_last_error=True)
kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
kernel32.CreateMutexW.restype = wintypes.HANDLE


def main() -> None:
    config = load_config()
    logger = setup_logger()
    mutex = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    if get_last_error() == ERROR_ALREADY_EXISTS:
        logger.warning("Another instance is already running; exiting")
        return

    stop_event = Event()

    def handle_shutdown(signum: int, _frame: object) -> None:
        logger.info("Shutdown signal received: %s", signum)
        stop_event.set()

    signal.signal(signal.SIGINT, handle_shutdown)
    signal.signal(signal.SIGTERM, handle_shutdown)

    monitor = WifiMonitor(config=config, logger=logger)
    tgate_agent = TgateSmartAgentAutomator(config=config.tgate, logger=logger)
    logger.info("Program started")
    if config.tgate.enabled:
        logger.info("Tgate automation enabled for window title: %s", config.tgate.window_title)
    else:
        logger.info("Tgate automation disabled")

    try:
        while not stop_event.is_set():
            try:
                monitor.check_and_reconnect()
                tgate_agent.try_fill_login()
            except Exception:
                logger.exception("Unexpected exception during monitor loop")

            stop_event.wait(config.check_interval)
    finally:
        logger.info("Program stopped")
        time.sleep(0.1)


if __name__ == "__main__":
    main()
