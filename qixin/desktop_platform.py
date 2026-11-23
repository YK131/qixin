"""Windows desktop integrations with app-local fallbacks on other systems."""
from __future__ import annotations

import ctypes
import os
import sys
from ctypes import wintypes
from threading import Event, Thread


class CaptureHotkey:
    """Listen for Ctrl+Alt+N without blocking Tk or calling it from a worker."""

    def __init__(self):
        self.pending = Event()
        self.stop = Event()
        self.thread: Thread | None = None
        if sys.platform == "win32":
            self.thread = Thread(target=self._listen, daemon=True)
            self.thread.start()

    def _listen(self) -> None:
        api = ctypes.windll.user32
        hotkey_id = 1
        ctrl_alt_no_repeat = 0x4003
        wm_hotkey = 0x0312
        if not api.RegisterHotKey(None, hotkey_id, ctrl_alt_no_repeat, ord("N")):
            return
        try:
            message = wintypes.MSG()
            while not self.stop.is_set():
                if api.PeekMessageW(ctypes.byref(message), None, wm_hotkey, wm_hotkey, 1):
                    self.pending.set()
                self.stop.wait(0.06)
        finally:
            api.UnregisterHotKey(None, hotkey_id)

    def take(self) -> bool:
        if not self.pending.is_set():
            return False
        self.pending.clear()
        return True

    def close(self) -> None:
        self.stop.set()
        if self.thread is not None:
            self.thread.join(timeout=0.25)


class MonitorInfo(ctypes.Structure):
    _fields_ = [
        ("size", wintypes.DWORD),
        ("monitor", wintypes.RECT),
        ("work", wintypes.RECT),
        ("flags", wintypes.DWORD),
    ]


def foreground_is_fullscreen() -> bool:
    if sys.platform != "win32":
        return False
    api = ctypes.windll.user32
    api.GetForegroundWindow.restype = wintypes.HWND
    api.GetClassNameW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
    api.GetWindowRect.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.RECT))
    api.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
    api.MonitorFromWindow.argtypes = (wintypes.HWND, wintypes.DWORD)
    api.MonitorFromWindow.restype = wintypes.HMONITOR
    api.GetMonitorInfoW.argtypes = (wintypes.HMONITOR, ctypes.POINTER(MonitorInfo))
    window = api.GetForegroundWindow()
    if not window:
        return False
    class_name = ctypes.create_unicode_buffer(64)
    api.GetClassNameW(window, class_name, len(class_name))
    if class_name.value in {"Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd"}:
        return False
    process = wintypes.DWORD()
    api.GetWindowThreadProcessId(window, ctypes.byref(process))
    if process.value == os.getpid():
        return False
    monitor = api.MonitorFromWindow(window, 2)
    screen = MonitorInfo()
    screen.size = ctypes.sizeof(screen)
    bounds = wintypes.RECT()
    if not monitor or not api.GetMonitorInfoW(monitor, ctypes.byref(screen)):
        return False
    if not api.GetWindowRect(window, ctypes.byref(bounds)):
        return False
    area = screen.monitor
    return (
        bounds.left <= area.left + 2 and bounds.top <= area.top + 2
        and bounds.right >= area.right - 2 and bounds.bottom >= area.bottom - 2
    )
