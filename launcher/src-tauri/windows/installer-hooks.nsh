!macro NSIS_HOOK_PREINSTALL
  DetailPrint "Stopping running Course Navigator services..."
  nsExec::ExecToLog 'powershell -NoProfile -ExecutionPolicy Bypass -Command "$$roots=@(''$INSTDIR'',$$env:LOCALAPPDATA+''\Course Navigator'',$$env:APPDATA+''\Course Navigator'');Get-CimInstance Win32_Process|?{$$p=$$_.ExecutablePath;$$c=$$_.CommandLine;$$m=$$false;foreach($$r in $$roots){if([string]::IsNullOrWhiteSpace($$r)){continue};if(($$p -and $$p.StartsWith($$r,[StringComparison]::OrdinalIgnoreCase))-or($$c -and $$c.IndexOf($$r,[StringComparison]::OrdinalIgnoreCase)-ge 0)){$$m=$$true;break}};$$m}|%{Stop-Process -Id $$_.ProcessId -Force -ErrorAction SilentlyContinue}"'
  Sleep 1000
!macroend
