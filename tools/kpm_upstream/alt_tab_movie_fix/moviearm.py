"""Arm the Alt Tab Patch's timer just before a movie: when the harness note ARM appears, take the
foreground away (taskbar) for 0.5 s and give it back to the game - then touch nothing."""
import ctypes, sys, time
from pathlib import Path
u = ctypes.windll.user32
notes = Path(sys.argv[3]); out = open(sys.argv[1], "w"); end = time.time() + float(sys.argv[2])
def fg(h):
    u.keybd_event(0x12, 0, 0, 0); u.keybd_event(0x12, 0, 2, 0); return u.SetForegroundWindow(h)
while time.time() < end:
    if notes.exists() and "ARM=" in notes.read_text(encoding="latin-1"):
        out.write(f"{time.strftime('%H:%M:%S')}.{int(time.time()*10)%10} away: {fg(u.FindWindowW('Shell_TrayWnd', None))}\n")
        time.sleep(0.5)
        g = u.FindWindowW(None, "Star Wars: Knights of the Old Republic")
        out.write(f"{time.strftime('%H:%M:%S')}.{int(time.time()*10)%10} back: {fg(g)}\n"); out.flush()
        break
    time.sleep(0.1)
