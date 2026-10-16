"""Watch who takes the foreground from KOTOR around its movies (user, 2026-10-10: with Alt Tab
Patch 1.8.2 a movie played full screen, then the game lost focus and did not come back).

Passive: reads window and display state only, changes nothing. Logs, with 0.1 s timestamps:
  FG     every foreground change - the window, its class and its process
  MIN/RESTORE  minimise start/end of any top-level window
  SHOW/HIDE    top-level windows of OTHER processes appearing or going away (overlays, toasts)
  STATE  on any change: the display mode, KOTOR's movie window and its main window
         (rectangle, hidden, minimised), and whether KOTOR owns the foreground
Runs until KOTOR has been gone for 10 s after having been seen (or --minutes runs out).

usage: focuswatch.py <log file> [--minutes N]
"""
import ctypes
import sys
import threading
import time
from ctypes import wintypes

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

GAME_TITLE = "Star Wars: Knights of the Old Republic"
MOVIE_TITLE = "SW Movie Player Window"
EVENT_SYSTEM_FOREGROUND, EVENT_SYSTEM_MINIMIZESTART, EVENT_SYSTEM_MINIMIZEEND = 0x0003, 0x0016, 0x0017
EVENT_OBJECT_SHOW, EVENT_OBJECT_HIDE = 0x8002, 0x8003
WINEVENT_OUTOFCONTEXT = 0
OBJID_WINDOW = 0
GA_ROOT = 2

WinEventProc = ctypes.WINFUNCTYPE(None, wintypes.HANDLE, wintypes.DWORD, wintypes.HWND, wintypes.LONG,
                                  wintypes.LONG, wintypes.DWORD, wintypes.DWORD)
user32.SetWinEventHook.restype = wintypes.HANDLE
user32.SetWinEventHook.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.HMODULE, WinEventProc,
                                   wintypes.DWORD, wintypes.DWORD, wintypes.DWORD]
user32.GetAncestor.restype = wintypes.HWND
user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
user32.GetForegroundWindow.restype = wintypes.HWND
user32.FindWindowW.restype = wintypes.HWND


class DEVMODEW(ctypes.Structure):
    _fields_ = [("dmDeviceName", wintypes.WCHAR * 32), ("dmSpecVersion", wintypes.WORD), ("dmDriverVersion", wintypes.WORD),
                ("dmSize", wintypes.WORD), ("dmDriverExtra", wintypes.WORD), ("dmFields", wintypes.DWORD),
                ("dmPositionX", wintypes.LONG), ("dmPositionY", wintypes.LONG), ("dmDisplayOrientation", wintypes.DWORD),
                ("dmDisplayFixedOutput", wintypes.DWORD), ("dmColor", ctypes.c_short), ("dmDuplex", ctypes.c_short),
                ("dmYResolution", ctypes.c_short), ("dmTTOption", ctypes.c_short), ("dmCollate", ctypes.c_short),
                ("dmFormName", wintypes.WCHAR * 32), ("dmLogPixels", wintypes.WORD), ("dmBitsPerPel", wintypes.DWORD),
                ("dmPelsWidth", wintypes.DWORD), ("dmPelsHeight", wintypes.DWORD), ("dmDisplayFlags", wintypes.DWORD),
                ("dmDisplayFrequency", wintypes.DWORD)]


lock = threading.Lock()
out = None
game_pid = None
game_seen = False


def stamp():
    t = time.time()
    return time.strftime("%H:%M:%S", time.localtime(t)) + f".{int(t * 10) % 10}"


def log(line):
    with lock:
        out.write(f"{stamp()} {line}\n")
        out.flush()


def pid_of(hwnd):
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


_names = {}


def process_name(pid):
    if pid in _names:
        return _names[pid]
    name = "?"
    h = kernel32.OpenProcess(0x1000, False, pid)          # PROCESS_QUERY_LIMITED_INFORMATION
    if h:
        buf = ctypes.create_unicode_buffer(520)
        size = wintypes.DWORD(520)
        if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            name = buf.value.rsplit("\\", 1)[-1]
        kernel32.CloseHandle(h)
    _names[pid] = name
    return name


def describe(hwnd):
    if not hwnd:
        return "(none)"
    title = ctypes.create_unicode_buffer(256)
    cls = ctypes.create_unicode_buffer(256)
    user32.GetWindowTextW(hwnd, title, 256)
    user32.GetClassNameW(hwnd, cls, 256)
    pid = pid_of(hwnd)
    return f"[{process_name(pid)} {pid}] '{title.value}' class={cls.value} hwnd={int(hwnd):#x}"


def on_event(hook, event, hwnd, id_object, id_child, thread, ms):
    try:
        if event == EVENT_SYSTEM_FOREGROUND:
            log(f"FG      {describe(hwnd)}")
        elif event in (EVENT_SYSTEM_MINIMIZESTART, EVENT_SYSTEM_MINIMIZEEND):
            log(f"{'MIN    ' if event == EVENT_SYSTEM_MINIMIZESTART else 'RESTORE'} {describe(hwnd)}")
        elif id_object == OBJID_WINDOW and id_child == 0 and hwnd and user32.GetAncestor(hwnd, GA_ROOT) == hwnd:
            pid = pid_of(hwnd)
            if pid == game_pid:
                return                                     # the game's own windows: STATE has them
            cls = ctypes.create_unicode_buffer(64)
            user32.GetClassNameW(hwnd, cls, 64)
            if cls.value in ("tooltips_class32", "#32768", "IME", "MSCTFIME UI"):
                return
            log(f"{'SHOW   ' if event == EVENT_OBJECT_SHOW else 'HIDE   '} {describe(hwnd)}")
    except Exception as exc:                               # never let a callback kill the hook
        log(f"error in event: {exc!r}")


def mode():
    dm = DEVMODEW()
    dm.dmSize = ctypes.sizeof(DEVMODEW)
    user32.EnumDisplaySettingsW(None, -1, ctypes.byref(dm))    # ENUM_CURRENT_SETTINGS
    return f"{dm.dmPelsWidth}x{dm.dmPelsHeight}"


def window_state(title):
    h = user32.FindWindowW(None, title)
    if not h:
        return None, "none"
    r = wintypes.RECT()
    user32.GetWindowRect(h, ctypes.byref(r))
    flags = ("" if user32.IsWindowVisible(h) else " hidden") + (" MINIMISED" if user32.IsIconic(h) else "")
    return h, f"({r.left},{r.top})-({r.right},{r.bottom}){flags}"


def poll(end):
    global game_pid, game_seen
    last, gone_since = None, None
    while time.time() < end:
        game, game_s = window_state(GAME_TITLE)
        movie, movie_s = window_state(MOVIE_TITLE)
        if game:
            game_pid = pid_of(game)
            if not game_seen:
                log(f"game found: pid {game_pid}")
            game_seen, gone_since = True, None
        elif game_seen:
            gone_since = gone_since or time.time()
            if time.time() - gone_since > 10:
                log("game gone for 10 s - stopping")
                return
        fg = user32.GetForegroundWindow()
        owner = "game" if fg and fg == game else "movie" if fg and fg == movie else \
            ("kotor-other" if fg and game_pid and pid_of(fg) == game_pid else "OTHER")
        now = (mode(), movie_s, game_s, owner)
        if now != last:
            log(f"STATE   display {now[0]}  movie {now[1]}  game {now[2]}  foreground={owner}")
            last = now
        time.sleep(0.1)


def main():
    global out
    args = sys.argv[1:]
    if not args:
        raise SystemExit(__doc__)
    minutes = float(args[args.index("--minutes") + 1]) if "--minutes" in args else 240
    out = open(args[0], "w", encoding="utf-8")
    log(f"focuswatch started (up to {minutes:g} min); foreground now {describe(user32.GetForegroundWindow())}")
    end = time.time() + minutes * 60
    poller = threading.Thread(target=poll, args=(end,), daemon=True)
    poller.start()

    proc = WinEventProc(on_event)
    hooks = [user32.SetWinEventHook(lo, hi, None, proc, 0, 0, WINEVENT_OUTOFCONTEXT)
             for lo, hi in ((EVENT_SYSTEM_FOREGROUND, EVENT_SYSTEM_FOREGROUND),
                            (EVENT_SYSTEM_MINIMIZESTART, EVENT_SYSTEM_MINIMIZEEND),
                            (EVENT_OBJECT_SHOW, EVENT_OBJECT_HIDE))]
    if not all(hooks):
        log("could not set every event hook")
    msg = wintypes.MSG()
    while poller.is_alive():
        # pump the hooks' messages without blocking, so the loop sees the poller end
        while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        time.sleep(0.02)
    for h in hooks:
        user32.UnhookWinEvent(h)
    log("focuswatch ended")


if __name__ == "__main__":
    main()
