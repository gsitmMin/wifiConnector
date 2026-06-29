from __future__ import annotations

import locale
import re
import subprocess
import time
from dataclasses import dataclass

from config import AppConfig


KOREAN_STATE_FIELD = "\uc0c1\ud0dc"
KOREAN_CONNECTED_STATE = "\uc5f0\uacb0\ub428"
UNKNOWN_STATUS_RECONNECT_INTERVAL = 60


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str

    def format_error(self) -> str:
        message = (self.stderr.strip() or self.stdout.strip()).replace("\r", "").replace("\n", " | ")
        return f"returncode={self.returncode}; {message or 'no output'}"

    def combined_output(self) -> str:
        return f"{self.stdout}\n{self.stderr}"

    def is_location_permission_error(self) -> bool:
        output = self.combined_output().casefold()
        return "location permission" in output or "privacy-location" in output


class WifiMonitor:
    def __init__(self, config: AppConfig, logger) -> None:
        self.config = config
        self.logger = logger
        self._status_query_blocked_logged = False
        self._last_unknown_status_reconnect_at = 0.0

    def check_and_reconnect(self) -> None:
        status = self.get_wifi_status()
        if status == "connected":
            return
        if status == "unknown":
            self._reconnect_on_unknown_status()
            return

        time.sleep(1)
        status = self.get_wifi_status()
        if status in {"connected", "unknown"}:
            return

        self.logger.info("Wi-Fi disconnected")
        self._retry_reconnect()

    def is_wifi_connected(self) -> bool:
        return self.get_wifi_status() != "disconnected"

    def get_wifi_status(self) -> str:
        result = self._run_netsh("wlan", "show", "interfaces")
        if result.returncode != 0:
            self.logger.warning("Failed to read Wi-Fi interface status: %s", result.format_error())
            if result.is_location_permission_error():
                fallback_status = self._get_windows_wifi_status_fallback()
                if fallback_status != "unknown":
                    self.logger.info("Wi-Fi status from Windows fallback: %s", fallback_status)
                    return fallback_status

                if not self._status_query_blocked_logged:
                    self.logger.warning(
                        "Wi-Fi status query is blocked by Windows location permission; treating status as unknown"
                    )
                    self._status_query_blocked_logged = True
                return "unknown"
            return "disconnected"

        state = self._extract_field(result.stdout, ("State", KOREAN_STATE_FIELD))
        ssid = self._extract_field(result.stdout, "SSID")

        connected_states = {"connected", KOREAN_CONNECTED_STATE}
        if state.lower() in connected_states or bool(ssid):
            return "connected"
        return "disconnected"

    def is_connected_to_target(self) -> bool:
        result = self._run_netsh("wlan", "show", "interfaces")
        if result.returncode != 0:
            self.logger.warning("Failed to read Wi-Fi interface status: %s", result.format_error())
            return False

        state = self._extract_field(result.stdout, ("State", KOREAN_STATE_FIELD))
        ssid = self._extract_field(result.stdout, "SSID")

        connected_states = {"connected", KOREAN_CONNECTED_STATE}
        return state.lower() in connected_states and ssid == self.config.ssid

    def target_ssid_available(self) -> bool:
        result = self._run_netsh("wlan", "show", "networks")
        if result.returncode != 0:
            self.logger.warning("Failed to scan Wi-Fi networks: %s", result.format_error())
            if result.is_location_permission_error() and self.target_profile_exists():
                self.logger.info("Wi-Fi scan is blocked by Windows location permission; target profile exists")
                return True
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
            self.logger.warning("Reconnect command failed: %s", result.format_error())
            return False

        time.sleep(2)

        status_result = self._run_netsh("wlan", "show", "interfaces")
        if status_result.returncode != 0:
            if status_result.is_location_permission_error():
                self.logger.warning(
                    "Reconnect command accepted, but status verification is blocked by Windows location permission"
                )
                return True

            self.logger.warning("Failed to verify Wi-Fi status after reconnect: %s", status_result.format_error())
            return False

        if self._is_connected_to_target(status_result.stdout):
            self.logger.info("Reconnected successfully")
            return True

        if self._is_wifi_connected_output(status_result.stdout):
            self.logger.info("Wi-Fi is connected; stopping reconnect attempts")
            return True

        self.logger.warning("Reconnect failed")
        return False

    def target_profile_exists(self) -> bool:
        result = self._run_netsh("wlan", "show", "profiles")
        if result.returncode != 0:
            self.logger.warning("Failed to read Wi-Fi profiles: %s", result.format_error())
            return False

        profiles = self._extract_profile_names(result.stdout)
        found = self.config.ssid in profiles
        if found:
            self.logger.info("Target Wi-Fi profile found")
        else:
            self.logger.info("Target Wi-Fi profile not found")
        return found

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

    def _reconnect_on_unknown_status(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_unknown_status_reconnect_at
        if elapsed < UNKNOWN_STATUS_RECONNECT_INTERVAL:
            return

        self._last_unknown_status_reconnect_at = now
        self.logger.info(
            "Wi-Fi status is unknown; attempting limited reconnect using saved profile"
        )
        if self.target_profile_exists():
            self.reconnect()

    def _is_connected_to_target(self, output: str) -> bool:
        state = self._extract_field(output, ("State", KOREAN_STATE_FIELD))
        ssid = self._extract_field(output, "SSID")

        connected_states = {"connected", KOREAN_CONNECTED_STATE}
        return state.lower() in connected_states and ssid == self.config.ssid

    def _is_wifi_connected_output(self, output: str) -> bool:
        state = self._extract_field(output, ("State", KOREAN_STATE_FIELD))
        ssid = self._extract_field(output, "SSID")

        connected_states = {"connected", KOREAN_CONNECTED_STATE}
        return state.lower() in connected_states or bool(ssid)

    def _get_windows_wifi_status_fallback(self) -> str:
        command = """
$profile = Get-NetConnectionProfile -InterfaceAlias 'Wi-Fi' -ErrorAction SilentlyContinue
if ($profile) {
    'connected'
    exit
}

$adapter = Get-NetAdapter -Name 'Wi-Fi' -ErrorAction SilentlyContinue
if (-not $adapter) {
    'unknown'
    exit
}

if ($adapter.Status -eq 'Up' -or $adapter.MediaConnectionState -eq 'Connected') {
    'connected'
} elseif ($adapter.Status -eq 'Disconnected' -or $adapter.MediaConnectionState -eq 'Disconnected') {
    'disconnected'
} else {
    'unknown'
}
"""
        try:
            completed = subprocess.run(
                ["powershell", "-NoProfile", "-Command", command],
                capture_output=True,
                text=True,
                encoding=locale.getpreferredencoding(False),
                errors="replace",
                shell=False,
                timeout=10,
            )
        except Exception:
            self.logger.exception("Failed to read Wi-Fi status from Windows fallback")
            return "unknown"

        if completed.returncode != 0:
            output = (completed.stderr.strip() or completed.stdout.strip()).replace("\r", "").replace("\n", " | ")
            self.logger.warning("Windows Wi-Fi status fallback failed: %s", output or "no output")
            return "unknown"

        status = completed.stdout.strip().splitlines()[-1].strip().lower() if completed.stdout.strip() else "unknown"
        return status if status in {"connected", "disconnected"} else "unknown"

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

    @staticmethod
    def _extract_profile_names(output: str) -> set[str]:
        profile_pattern = re.compile(r"^\s*.+Profile\s*:\s*(.+?)\s*$", re.IGNORECASE | re.MULTILINE)
        return {match.group(1).strip() for match in profile_pattern.finditer(output)}
