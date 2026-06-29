from __future__ import annotations

import re
import time
from ctypes import WINFUNCTYPE, WinDLL, addressof, byref, create_unicode_buffer, wintypes

from config import TgateConfig


LOGIN_BUTTON_RE = r"(?i)(login|log in|sign in|connect|ok|confirm|로그인|확인|접속|연결)"
BM_CLICK = 0x00F5
WM_SETTEXT = 0x000C
SMTO_ABORTIFHUNG = 0x0002
WINDOW_MESSAGE_TIMEOUT_MS = 1000

user32 = WinDLL("user32", use_last_error=True)
EnumWindowsProc = WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
EnumChildProc = WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

user32.EnumWindows.argtypes = [EnumWindowsProc, wintypes.LPARAM]
user32.EnumWindows.restype = wintypes.BOOL
user32.EnumChildWindows.argtypes = [wintypes.HWND, EnumChildProc, wintypes.LPARAM]
user32.EnumChildWindows.restype = wintypes.BOOL
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, wintypes.INT]
user32.GetWindowTextW.restype = wintypes.INT
user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, wintypes.INT]
user32.GetClassNameW.restype = wintypes.INT
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsWindowVisible.restype = wintypes.BOOL
user32.IsWindowEnabled.argtypes = [wintypes.HWND]
user32.IsWindowEnabled.restype = wintypes.BOOL
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.SetForegroundWindow.restype = wintypes.BOOL
user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.SendMessageW.restype = wintypes.LPARAM
user32.SetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPCWSTR]
user32.SetWindowTextW.restype = wintypes.BOOL
user32.SendMessageTimeoutW.argtypes = [
    wintypes.HWND,
    wintypes.UINT,
    wintypes.WPARAM,
    wintypes.LPARAM,
    wintypes.UINT,
    wintypes.UINT,
    wintypes.PDWORD,
]
user32.SendMessageTimeoutW.restype = wintypes.LPARAM
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, wintypes.LPDWORD]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD


class TgateSmartAgentAutomator:
    def __init__(self, config: TgateConfig, logger) -> None:
        self.config = config
        self.logger = logger
        self._available: bool | None = None
        self._last_fill_by_handle: dict[int, float] = {}

    def try_fill_login(self) -> bool:
        if not self.config.enabled:
            return False

        self._dismiss_alerts()
        return self._try_fill_with_win32()

    def _try_fill_with_pywinauto(self) -> bool:
        if not self._is_pywinauto_available():
            return False

        from pywinauto import Desktop
        from pywinauto.keyboard import send_keys

        title_pattern = f"(?i).*{re.escape(self.config.window_title)}.*"

        try:
            windows = Desktop(backend="uia").windows(title_re=title_pattern, visible_only=True)
        except Exception:
            self.logger.exception("Failed to scan Tgate smart Agent windows")
            return False

        for window in windows:
            try:
                handle = int(window.handle)
                if self._was_recently_filled(handle):
                    continue

                edits = self._find_login_edits(window)
                if len(edits) < 2:
                    continue

                self.logger.info("Tgate smart Agent login fields detected")
                edits[0].set_edit_text(self.config.username)
                edits[1].set_edit_text(self.config.password)

                if self.config.submit:
                    self._submit(window, send_keys)

                self._last_fill_by_handle[handle] = time.monotonic()
                self.logger.info("Tgate smart Agent credentials entered")
                return True
            except Exception:
                self.logger.exception("Failed to fill Tgate smart Agent login fields")

        return False

    def _try_fill_with_win32(self) -> bool:
        for window in _find_top_windows(self.config.window_title):
            handle = int(window)
            if self._was_recently_filled(handle):
                continue

            controls = _find_child_controls(window)
            edits = [
                control
                for control in controls
                if control.class_name == "Edit" and control.visible and control.enabled
            ]
            if len(edits) < 2:
                continue

            buttons = [
                control
                for control in controls
                if control.class_name == "Button" and control.visible and control.enabled
            ]

            self.logger.info("Tgate Smart Agent login fields detected")
            if not _set_text(edits[0].handle, self.config.username):
                self.logger.warning("Failed to enter Tgate username")
                return False
            if not _set_text(edits[1].handle, self.config.password):
                self.logger.warning("Failed to enter Tgate password")
                return False

            if self.config.submit:
                if not _click_matching_button(buttons):
                    self.logger.warning("Tgate login button was not clicked")
                    return False

            self._last_fill_by_handle[handle] = time.monotonic()
            self.logger.info("Tgate Smart Agent credentials entered")
            return True

        return False

    def _dismiss_alerts(self) -> None:
        for window in _find_top_windows(self.config.window_title):
            controls = _find_child_controls(window)
            visible_edits = [
                control
                for control in controls
                if control.class_name == "Edit" and control.visible and control.enabled
            ]
            if len(visible_edits) >= 2:
                continue

            buttons = [
                control
                for control in controls
                if control.class_name == "Button" and control.visible and control.enabled
            ]
            if _click_alert_button(buttons):
                self.logger.info("Tgate alert dialog dismissed")

    def _is_pywinauto_available(self) -> bool:
        if self._available is not None:
            return self._available

        try:
            import pywinauto  # noqa: F401
        except ImportError:
            self._available = False
        else:
            self._available = True

        return self._available

    @staticmethod
    def _find_login_edits(window) -> list:
        edits = window.descendants(control_type="Edit")
        return [edit for edit in edits if edit.is_visible() and edit.is_enabled()]

    @staticmethod
    def _submit(window, send_keys) -> None:
        buttons = window.descendants(control_type="Button")
        for button in buttons:
            if not button.is_visible() or not button.is_enabled():
                continue
            label = (button.window_text() or "").strip()
            if re.search(LOGIN_BUTTON_RE, label):
                button.click_input()
                return

        window.set_focus()
        send_keys("{ENTER}")

    def _was_recently_filled(self, handle: int) -> bool:
        last_fill = self._last_fill_by_handle.get(handle)
        return last_fill is not None and time.monotonic() - last_fill < 60


class Win32Control:
    def __init__(self, handle: int, class_name: str, text: str, visible: bool, enabled: bool) -> None:
        self.handle = handle
        self.class_name = class_name
        self.text = text
        self.visible = visible
        self.enabled = enabled


def _find_top_windows(title_part: str) -> list[int]:
    handles: list[int] = []
    needle = title_part.casefold()

    def callback(hwnd, _lparam) -> bool:
        title = _get_window_text(hwnd)
        if needle in title.casefold():
            handles.append(int(hwnd))
        return True

    user32.EnumWindows(EnumWindowsProc(callback), 0)
    return handles


def _find_child_controls(parent_handle: int) -> list[Win32Control]:
    controls: list[Win32Control] = []

    def callback(hwnd, _lparam) -> bool:
        controls.append(
            Win32Control(
                handle=int(hwnd),
                class_name=_get_class_name(hwnd),
                text=_get_window_text(hwnd),
                visible=bool(user32.IsWindowVisible(hwnd)),
                enabled=bool(user32.IsWindowEnabled(hwnd)),
            )
        )
        return True

    user32.EnumChildWindows(parent_handle, EnumChildProc(callback), 0)
    return controls


def _get_window_text(handle: int) -> str:
    buffer = create_unicode_buffer(512)
    user32.GetWindowTextW(handle, buffer, len(buffer))
    return buffer.value


def _get_class_name(handle: int) -> str:
    buffer = create_unicode_buffer(256)
    user32.GetClassNameW(handle, buffer, len(buffer))
    return buffer.value


def _set_text(handle: int, value: str) -> bool:
    buffer = create_unicode_buffer(value)
    result = wintypes.DWORD()
    sent = user32.SendMessageTimeoutW(
        handle,
        WM_SETTEXT,
        0,
        addressof(buffer),
        SMTO_ABORTIFHUNG,
        WINDOW_MESSAGE_TIMEOUT_MS,
        byref(result),
    )
    return bool(sent)


def _click_matching_button(buttons: list[Win32Control]) -> bool:
    for button in buttons:
        if re.search(LOGIN_BUTTON_RE, button.text):
            result = wintypes.DWORD()
            user32.SetForegroundWindow(button.handle)
            sent = user32.SendMessageTimeoutW(
                button.handle,
                BM_CLICK,
                0,
                0,
                SMTO_ABORTIFHUNG,
                WINDOW_MESSAGE_TIMEOUT_MS,
                byref(result),
            )
            return bool(sent)
    return False


def _click_alert_button(buttons: list[Win32Control]) -> bool:
    for button in buttons:
        if button.text.strip() in {"확인", "OK", "Ok", "ok"}:
            result = wintypes.DWORD()
            user32.SetForegroundWindow(button.handle)
            sent = user32.SendMessageTimeoutW(
                button.handle,
                BM_CLICK,
                0,
                0,
                SMTO_ABORTIFHUNG,
                WINDOW_MESSAGE_TIMEOUT_MS,
                byref(result),
            )
            return bool(sent)
    return False
