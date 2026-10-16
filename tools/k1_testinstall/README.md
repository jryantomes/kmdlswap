# K1 test installs

Two throwaway vanilla KOTOR 1 installs for testing HoloPatcher installs and mod
stacks without touching the live Steam game:

| Folder | From | Notes |
|---|---|---|
| `D:\KOTOR_GOG` | GOG offline installer 1.03 (29871) | Installer kept in `D:\Downloads\KOTOR_GOG_installer`. The GOG exe has no DRM and has the 4GB flag set (`swkotor.exe.before-laa` is the untouched original). `swkotor.ini` is the live one (`swkotor.ini.gog-default` is GOG's). Registered with Windows, so HoloPatcher can detect it. |
| `D:\KOTOR_Test` | copied from the live Steam install | Every file is hash-checked against Steam's depot manifest. `dialog.tlk` comes from K1CP's backup and `swpc_tex_gui.erf` from the GOG install. `swkotor.exe` is the live Steamless-unpacked 4GB exe (the SteamStub exe would relaunch the live install). |

The GOG game data is byte-identical to Steam's vanilla files (15,364 of them).
The only differences are the exe, the ini, two logo movies and the launcher
files.

```
python tools\k1_testinstall\make_test_install.py reset  D:\KOTOR_GOG   # back to vanilla (~10 s)
python tools\k1_testinstall\make_test_install.py verify D:\KOTOR_GOG   # list changes, touch nothing
python tools\k1_testinstall\make_test_install.py build  D:\KOTOR_Test  # rebuild the Steam copy (~2 min)
python tools\k1_testinstall\make_test_install.py adopt  <folder>       # take a fresh install as a baseline
```

- Each install keeps `.k1_testinstall.json` (path -> size, SHA-1 of every
  file) and `_baseline\`, which holds copies of the files the live Steam
  install can't restore.
- `reset` restores changed files and moves anything added into
  `_reset_removed\<timestamp>\`. It deletes nothing, and it never touches
  `saves\`.
- The script refuses to run on the live install, and it refuses to
  reset/verify any folder it hasn't built or adopted.
- The Steam reference is `depotcache\32371_4122010938027300909.manifest`
  (build 4143502), read by `steam_manifest.py`.
