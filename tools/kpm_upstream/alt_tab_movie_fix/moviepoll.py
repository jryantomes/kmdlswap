"""While KOTOR runs: twice a second, the primary display's mode and the movie window's rectangle
(user, 2026-10-04: movies in the top-left corner, not full screen). Writes one line per change."""
import ctypes
import sys
import time
from ctypes import wintypes

user32 = ctypes.windll.user32


class DEVMODEW(ctypes.Structure):
    _fields_ = [("dmDeviceName", wintypes.WCHAR * 32), ("dmSpecVersion", wintypes.WORD), ("dmDriverVersion", wintypes.WORD),
                ("dmSize", wintypes.WORD), ("dmDriverExtra", wintypes.WORD), ("dmFields", wintypes.DWORD),
                ("dmPositionX", wintypes.LONG), ("dmPositionY", wintypes.LONG), ("dmDisplayOrientation", wintypes.DWORD),
                ("dmDisplayFixedOutput", wintypes.DWORD), ("dmColor", ctypes.c_short), ("dmDuplex", ctypes.c_short),
                ("dmYResolution", ctypes.c_short), ("dmTTOption", ctypes.c_short), ("dmCollate", ctypes.c_short),
                ("dmFormName", wintypes.WCHAR * 32), ("dmLogPixels", wintypes.WORD), ("dmBitsPerPel", wintypes.DWORD),
                ("dmPelsWidth", wintypes.DWORD), ("dmPelsHeight", wintypes.DWORD), ("dmDisplayFlags", wintypes.DWORD),
                ("dmDisplayFrequency", wintypes.DWORD)]


def mode():
    dm = DEVMODEW(); dm.dmSize = ctypes.sizeof(DEVMODEW)
    user32.EnumDisplaySettingsW(None, -1, ctypes.byref(dm))       # ENUM_CURRENT_SETTINGS
    return f"{dm.dmPelsWidth}x{dm.dmPelsHeight}"


def rect(title):
    h = user32.FindWindowW(None, title)
    if not h:
        return None
    r = wintypes.RECT(); user32.GetWindowRect(h, ctypes.byref(r))
    vis = user32.IsWindowVisible(h)
    return f"({r.left},{r.top})-({r.right},{r.bottom}){'' if vis else ' hidden'}"


out = open(sys.argv[1], "w")
end = time.time() + float(sys.argv[2])
last = None
while time.time() < end:
    now = (mode(), rect("SW Movie Player Window"), rect("Star Wars: Knights of the Old Republic"))
    if now != last:
        out.write(f"{time.strftime('%H:%M:%S') + f'.{int(time.time()*10)%10}'} display {now[0]}  movie window {now[1]}  game window {now[2]}\n"); out.flush()
        last = now
    time.sleep(0.1)
