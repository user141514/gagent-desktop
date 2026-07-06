"""
Win32 console window utilities: enumerate, activate, screenshot, send input.
Works with ConsoleWindowClass (cmd.exe, claude.exe, conhost-hosted terminals).
"""
import base64
import ctypes
import io
from typing import Optional

import psutil
import win32api
import win32con
import win32gui
import win32process


def set_dpi_aware():
    """Call once to ensure win32 coords match physical pixels."""
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def enumerate_console_windows():
    """
    Return list of dicts for all visible ConsoleWindowClass windows.
    Each dict: {hwnd, pid, proc_name, title, class_name}
    Sorted: claude first, then cmd/powershell, then others.
    """
    results = []
    seen = set()

    def _enum_cb(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return
        class_name = win32gui.GetClassName(hwnd)
        if class_name not in ("ConsoleWindowClass", "CASCADIA_HOSTING_WINDOW_CLASS", "VirtualConsoleClass"):
            return
        title = win32gui.GetWindowText(hwnd)
        if not title:
            return
        if hwnd in seen:
            return
        seen.add(hwnd)
        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            proc_name = psutil.Process(pid).name().lower()
        except Exception:
            pid = 0
            proc_name = "unknown"
        results.append({
            "hwnd": hwnd,
            "pid": pid,
            "proc_name": proc_name,
            "title": title,
            "class_name": class_name,
        })

    win32gui.EnumWindows(_enum_cb, None)

    def sort_key(w):
        n = w["proc_name"]
        if "claude" in n:
            return (0, w["title"])
        if "cmd" in n or "powershell" in n or "pwsh" in n:
            return (1, w["title"])
        return (2, w["title"])

    results.sort(key=sort_key)
    return results


def activate_window(hwnd: int) -> bool:
    """Bring window to foreground and restore if minimized."""
    try:
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32gui.SetForegroundWindow(hwnd)
        return True
    except Exception:
        return False


def capture_window_image_b64(hwnd: int) -> Optional[str]:
    """
    Capture window as PNG via PrintWindow (works in background).
    Returns base64-encoded PNG string, or None on failure.
    """
    try:
        import win32ui
        from PIL import Image

        left, top, right, bottom = win32gui.GetWindowRect(hwnd)
        w, h = right - left, bottom - top
        if w <= 0 or h <= 0:
            return None

        hwnd_dc = win32gui.GetWindowDC(hwnd)
        mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
        save_dc = mfc_dc.CreateCompatibleDC()
        bmp = win32ui.CreateBitmap()
        bmp.CreateCompatibleBitmap(mfc_dc, w, h)
        save_dc.SelectObject(bmp)

        # PW_RENDERFULLCONTENT=2 for GPU/layered windows; fallback to 0
        ok = ctypes.windll.user32.PrintWindow(hwnd, save_dc.GetSafeHdc(), 2)
        if not ok:
            ctypes.windll.user32.PrintWindow(hwnd, save_dc.GetSafeHdc(), 0)

        bmp_info = bmp.GetInfo()
        bmp_bits = bmp.GetBitmapBits(True)
        img = Image.frombuffer(
            "RGB",
            (bmp_info["bmWidth"], bmp_info["bmHeight"]),
            bmp_bits, "raw", "BGRX", 0, 1,
        )

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode()

        save_dc.DeleteDC()
        mfc_dc.DeleteDC()
        win32gui.ReleaseDC(hwnd, hwnd_dc)
        win32ui.DeleteObject(bmp.GetHandle())
        return b64
    except Exception:
        return None


def send_text_to_console(hwnd: int, text: str):
    """Send text character-by-character via WM_CHAR."""
    for ch in text:
        win32api.SendMessage(hwnd, win32con.WM_CHAR, ord(ch), 0)


def send_enter_to_console(hwnd: int):
    """Send Enter (carriage return) to console."""
    win32api.SendMessage(hwnd, win32con.WM_CHAR, ord('\r'), 0)


def send_ctrl_c(hwnd: int):
    """Send Ctrl+C to interrupt running process in console."""
    # GenerateConsoleCtrlEvent is more reliable but requires same process group.
    # Fallback: inject ETX character (0x03) which conhost interprets as Ctrl+C.
    win32api.SendMessage(hwnd, win32con.WM_CHAR, 0x03, 0)


# ── Initialize DPI awareness on import ──
set_dpi_aware()