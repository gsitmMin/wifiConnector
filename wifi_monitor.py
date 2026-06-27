from __future__ import annotations

import locale
import re
import subprocess
import time
from dataclasses import dataclass

from config import AppConfig


KOREAN_STATE_FIELD = "\uc0c1\ud0dc"
KOREAN_CONNECTED_STATE = "\uc5f0\uacb0\ub428"


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


class WifiMonitor:
    def __init__(self, config: AppConfig, logger) -> None:
        self.config = config
        self.logger = logger

    def check_and_reconnect(self) -> None:
        if self.is_wifi_connected():
            return

        time.sleep(1)
        if self.is_wifi_connected():
            return

        self.logger.info("Wi-Fi disconnected")
        self._retry_reconnect()

    def is_wifi_connected(self) -> bool:
        result = self._run_netsh("wlan", "show", "interfaces")
        if result.returncode != 0:
            self.logger.warning("Failed to read Wi-Fi interface status: %s", result.stderr.strip())
            return False

        state = self._extract_field(result.stdout, ("State", KOREAN_STATE_FIELD))
        ssid = self._extract_field(result.stdout, "SSID")

        connected_states = {"connected", KOREAN_CONNECTED_STATE}
        return state.lower() in connected_states or bool(ssid)

    def is_connected_to_target(self) -> bool:
        result = self._run_netsh("wlan", "show", "interfaces")
        if result.returncode != 0:
            self.logger.warning("Failed to read Wi-Fi interface status: %s", result.stderr.strip())
            return False

        state = self._extract_field(result.stdout, ("State", KOREAN_STATE_FIELD))
        ssid = self._extract_field(result.stdout, "SSID")

        connected_states = {"connected", KOREAN_CONNECTED_STATE}
        return state.lower() in connected_states and ssid == self.config.ssid

    def target_ssid_available(self) -> bool:
        result = self._run_netsh("wlan", "show", "networks")
        if result.returncode != 0:
            self.logger.warning("Failed to scan Wi-Fi networks: %s", result.stderr.strip())
            return False

        available_ssids = self._extract_ssids(result.stdout)
        found = self.config.ssid in available_ssids

        if found:
            self.logger.info("Target SSID found")
        else:
            self.logger.info("Target SSID not found")

        return found

    def reconnect(self) -> bool:
        self.logger.info("Reconnect attempt")
        result = self._run_netsh("wlan", "connect", f'name="{self.config.ssid}"')

        if result.returncode != 0:
            self.logger.warning("Reconnect command failed: %s", result.stderr.strip() or result.stdout.strip())
            return False

        time.sleep(2)
        if self.is_connected_to_target():
            self.logger.info("Reconnected successfully")
            return True

        if self.is_wifi_connected():
            self.logger.info("Wi-Fi is connected; stopping reconnect attempts")
            return True

        self.logger.warning("Reconnect failed")
        return False

    def _retry_reconnect(self) -> None:
        for attempt in range(1, self.config.max_retry + 1):
            if self.is_wifi_connected():
                self.logger.info("Wi-Fi is already connected; stopping reconnect attempts")
                return

            self.logger.info("Reconnect retry %s/%s", attempt, self.config.max_retry)

            try:
                if self.target_ssid_available() and self.reconnect():
                    return
            except Exception:
                self.logger.exception("Exception occurred while reconnecting")

            if attempt < self.config.max_retry:
                time.sleep(self.config.retry_interval)

        self.logger.warning("Reconnect failed after %s retries", self.config.max_retry)

    @staticmethod
    def _run_netsh(*args: str) -> CommandResult:
        completed = subprocess.run(
            ["netsh", *args],
            capture_output=True,
            text=True,
            encoding=locale.getpreferredencoding(False),
            errors="replace",
            shell=False,
            timeout=30,
        )
        return CommandResult(
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )

    @staticmethod
    def _extract_field(output: str, field_names: str | tuple[str, ...]) -> str:
        names = (field_names,) if isinstance(field_names, str) else field_names
        for field_name in names:
            pattern = re.compile(rf"^\s*{re.escape(field_name)}\s*:\s*(.+?)\s*$", re.IGNORECASE | re.MULTILINE)
            match = pattern.search(output)
            if match:
                return match.group(1).strip()
        return ""

    @staticmethod
    def _extract_ssids(output: str) -> set[str]:
        ssid_pattern = re.compile(r"^\s*SSID\s+\d+\s*:\s*(.+?)\s*$", re.IGNORECASE | re.MULTILINE)
        return {match.group(1).strip() for match in ssid_pattern.finditer(output)}
