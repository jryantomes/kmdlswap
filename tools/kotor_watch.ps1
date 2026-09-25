# kotor_watch.ps1 - log KOTOR's memory and thread count while it runs, to see what fills it.
# Waits for swkotor.exe, then every 10 s records working set, private bytes, virtual size
# (the 32-bit address space that ran out: 4 GB with LAA), threads and handles, until it exits.
# usage: powershell -File tools\kotor_watch.ps1 [csv path]
param([string]$Out = "C:\Users\jryan\mdl swap\builds\kotor-watch.csv")
while (-not (Get-Process swkotor -ErrorAction SilentlyContinue)) { Start-Sleep -Seconds 5 }
"time,working_mb,private_mb,virtual_mb,threads,handles" | Set-Content -Encoding utf8 $Out
while ($p = Get-Process swkotor -ErrorAction SilentlyContinue) {
    $p = $p | Select-Object -First 1
    "{0},{1:N0},{2:N0},{3:N0},{4},{5}" -f (Get-Date -Format "HH:mm:ss"), ($p.WorkingSet64/1MB), ($p.PrivateMemorySize64/1MB),
        ($p.VirtualMemorySize64/1MB), $p.Threads.Count, $p.HandleCount | Add-Content -Encoding utf8 $Out
    Start-Sleep -Seconds 10
}
"exited $(Get-Date -Format 'HH:mm:ss')" | Add-Content -Encoding utf8 $Out
