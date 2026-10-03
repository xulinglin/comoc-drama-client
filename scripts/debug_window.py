"""调试脚本：检查 CDTV 窗口的最大化状态。
用法：先启动客户端并点最大化，然后运行本脚本。
"""
import ctypes
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)

user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
user32.FindWindowW.restype = wintypes.HWND
user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
user32.IsZoomed.argtypes = [wintypes.HWND]
user32.IsZoomed.restype = wintypes.BOOL
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
user32.MonitorFromWindow.restype = wintypes.HMONITOR


class MonitorInfo(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
    ]


user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(MonitorInfo)]
user32.GetMonitorInfoW.restype = wintypes.BOOL

hwnd = user32.FindWindowW(None, "CDTV")
print(f"hwnd: {hwnd}")

if not hwnd:
    print("没找到 CDTV 窗口，确认客户端已启动")
    raise SystemExit(0)

style = user32.GetWindowLongPtrW(hwnd, -16)
ex_style = user32.GetWindowLongPtrW(hwnd, -20)
print(f"style     : {style:#x}  WS_MAXIMIZE={bool(style & 0x01000000)}  WS_BORDER={bool(style & 0x00800000)}  WS_CAPTION={bool(style & 0x00C00000)}")
print(f"ex_style  : {ex_style:#x}  WS_EX_TOPMOST={bool(ex_style & 0x00000008)}  WS_EX_TOOLWINDOW={bool(ex_style & 0x00000080)}")
print(f"IsZoomed  : {bool(user32.IsZoomed(hwnd))}")

wr = wintypes.RECT()
user32.GetWindowRect(hwnd, ctypes.byref(wr))
print(f"window rect: ({wr.left},{wr.top}) - ({wr.right},{wr.bottom})  size = {wr.right-wr.left} x {wr.bottom-wr.top}")

cr = wintypes.RECT()
user32.GetClientRect(hwnd, ctypes.byref(cr))
# 客户区是相对窗口的，转成屏幕坐标
import struct
pt = wintypes.POINT(0, 0)
user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
user32.ClientToScreen(hwnd, ctypes.byref(pt))
print(f"client rect (screen): ({pt.x},{pt.y}) - ({pt.x + cr.right-cr.left},{pt.y + cr.bottom-cr.top})  size = {cr.right-cr.left} x {cr.bottom-cr.top}")

hmon = user32.MonitorFromWindow(hwnd, 2)
mi = MonitorInfo()
mi.cbSize = ctypes.sizeof(mi)
if user32.GetMonitorInfoW(hmon, ctypes.byref(mi)):
    print(f"monitor  rect: ({mi.rcMonitor.left},{mi.rcMonitor.top}) - ({mi.rcMonitor.right},{mi.rcMonitor.bottom})  size = {mi.rcMonitor.right-mi.rcMonitor.left} x {mi.rcMonitor.bottom-mi.rcMonitor.top}")
    print(f"work area  : ({mi.rcWork.left},{mi.rcWork.top}) - ({mi.rcWork.right},{mi.rcWork.bottom})  size = {mi.rcWork.right-mi.rcWork.left} x {mi.rcWork.bottom-mi.rcWork.top}")
    print()
    print(f"窗口矩形是否 == 工作区: {wr.left == mi.rcWork.left and wr.top == mi.rcWork.top and wr.right == mi.rcWork.right and wr.bottom == mi.rcWork.bottom}")
    print(f"窗口矩形是否 == 显示器: {wr.left == mi.rcMonitor.left and wr.top == mi.rcMonitor.top and wr.right == mi.rcMonitor.right and wr.bottom == mi.rcMonitor.bottom}")
