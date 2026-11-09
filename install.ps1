# Windows installer, run by install.bat. ASCII only on purpose (Windows PowerShell 5.1 reads files as ANSI).
$ErrorActionPreference = "Stop"
$Repo = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Repo
$TaskName = "AI Team Bot"
$env:PYTHONIOENCODING = "utf-8"

# 1) Python 3.10+
$Py = $null
$probe = "import sys; print(sys.executable if sys.version_info >= (3,10) else '')"
foreach ($cand in @(@("py", "-3"), @("python"), @("python3"))) {
    try {
        $extra = @($cand | Select-Object -Skip 1)
        $exe = & $cand[0] @extra -c $probe 2>$null
        if ($LASTEXITCODE -eq 0 -and $exe -and (Test-Path $exe.Trim())) { $Py = $exe.Trim(); break }
    } catch {}
}
if (-not $Py) {
    Write-Host "Python 3.10+ topilmadi. O'rnatilmoqda (winget)..."
    try {
        winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
        Write-Host ""
        Write-Host "Python o'rnatildi. Shu oynani yoping va install.bat ni QAYTA ishga tushiring."
    } catch {
        Write-Host "winget ishlamadi. Python'ni qo'lda o'rnating: https://www.python.org/downloads/"
        Write-Host "(o'rnatishda 'Add python.exe to PATH' belgisini qo'ying), so'ng install.bat ni qayta ishga tushiring."
    }
    exit 1
}
$PyW = Join-Path (Split-Path $Py) "pythonw.exe"
if (-not (Test-Path $PyW)) { $PyW = $Py }
Write-Host "Python: $Py"

# 2) .env + token + packages
& $Py "$Repo\tgbot\service.py" --setup
if ($LASTEXITCODE -ne 0) { Write-Host "Paketlar hozir o'rnatilmadi - xizmat internet bo'lganda o'zi o'rnatadi." }

# 3) autostart: Task Scheduler (at logon, restart on failure, works on battery, no time limit)
$Service = "`"$Repo\tgbot\service.py`""
$ok = $false
try {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    $action   = New-ScheduledTaskAction -Execute $PyW -Argument $Service -WorkingDirectory $Repo
    $trigger  = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
                -StartWhenAvailable -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
                -ExecutionTimeLimit (New-TimeSpan -Seconds 0) -MultipleInstances IgnoreNew
    $principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings `
        -Principal $principal -Description "AI Team Telegram bot: avto-start va avto-ulanish" | Out-Null
    Start-ScheduledTask -TaskName $TaskName
    $ok = $true
    $How = "Task Scheduler ('$TaskName')"
} catch {
    Write-Host "Task Scheduler ishlamadi ($($_.Exception.Message)). Startup papkasi ishlatiladi."
}
if (-not $ok) {
    $Startup = [Environment]::GetFolderPath("Startup")
    $Vbs = Join-Path $Startup "ai-team-bot.vbs"
    $line = 'CreateObject("WScript.Shell").Run """' + $PyW + '"" ""' + "$Repo\tgbot\service.py" + '""", 0, False'
    Set-Content -Path $Vbs -Value $line -Encoding ASCII
    Start-Process -FilePath $PyW -ArgumentList $Service -WorkingDirectory $Repo -WindowStyle Hidden
    $How = "Startup papkasi ($Vbs)"
}

Start-Sleep -Seconds 3
Write-Host ""
Write-Host "TAYYOR. O'rnatildi: $How"
Write-Host "  - Windows'ga kirganingizda bot o'zi ishga tushadi va fonda ishlaydi (oyna ochilmaydi)."
Write-Host "  - Internet uzilib qaytsa yoki noutbuk uyqudan uyg'onsa - o'zi qayta ulanadi."
Write-Host "  - .env ni o'zgartirsangiz - bot o'zi qayta yoqiladi."
Write-Host ""
Write-Host "Holat va loglar:  status.bat  (yoki: `"$Py`" tgbot\service.py --status)"
Write-Host "O'chirish:        uninstall.bat"
if (-not (Get-Command claude -ErrorAction SilentlyContinue)) {
    Write-Host ""
    Write-Host "AI agent (botga oddiy matn -> Claude Code) uchun Claude Code kerak. PowerShell'da:"
    Write-Host "  irm https://claude.ai/install.ps1 | iex     so'ng   claude   (bir marta kiring)"
}
