"""When KOTOR's movie window shows: 6 s later take the foreground away (the taskbar) for 1 s and
give it back to the movie window - an alt-tab during a movie. Logs what it did."""
import ctypes, sys, time
u = ctypes.windll.user32
out = open(sys.argv[1], "w"); end = time.time() + float(sys.argv[2])
def fg(h):
    u.keybd_event(0x12, 0, 0, 0); u.keybd_event(0x12, 0, 2, 0); return u.SetForegroundWindow(h)
while time.time() < end:
    m = u.FindWindowW(None, "SW Movie Player Window")
    if m and u.IsWindowVisible(m):
        time.sleep(6)
        t = u.FindWindowW(None, "Star Wars: Knights of the Old Republic"); u.ShowWindowAsync(t, 9)
        out.write(f"{time.strftime('%H:%M:%S')} main window activated: {fg(t)}\n"); out.flush()
        time.sleep(1)
        m2 = u.FindWindowW(None, "SW Movie Player Window")
        g = m2 or u.FindWindowW(None, "Star Wars: Knights of the Old Republic")
        out.write(f"{time.strftime('%H:%M:%S')} back to {'movie' if m2 else 'game'}: {fg(g)}\n"); out.flush()
        break
    time.sleep(0.1)
