; Always show the language selector because older installers can cache English in HKCU.
!define MUI_LANGDLL_ALWAYSSHOW

; A process belongs to Course Navigator when its executable lives under one of
; its directories, or its command line runs the course_navigator app from one.
; Paths are matched with a trailing separator so sibling folders never match.
!macro NSIS_HOOK_PREINSTALL
  DetailPrint "Stopping running Course Navigator services..."
  nsExec::ExecToLog 'powershell -NoProfile -ExecutionPolicy Bypass -Command "$$self=$$PID;$$roots=@(''$INSTDIR'',$$env:LOCALAPPDATA+''\Course Navigator'',$$env:APPDATA+''\Course Navigator'');Get-Process course-navigator-launcher -ErrorAction SilentlyContinue|%{Stop-Process -Id $$_.Id -Force -ErrorAction SilentlyContinue;Wait-Process -Id $$_.Id -Timeout 5 -ErrorAction SilentlyContinue};Get-CimInstance Win32_Process|?{if($$_.ProcessId -eq $$self){$$false}else{$$p=$$_.ExecutablePath;$$c=$$_.CommandLine;$$m=$$false;foreach($$r in $$roots){if([string]::IsNullOrWhiteSpace($$r)){continue};$$d=$$r.TrimEnd([char]92)+[char]92;if(($$p -and $$p.StartsWith($$d,[StringComparison]::OrdinalIgnoreCase))-or($$c -and $$c.IndexOf($$d,[StringComparison]::OrdinalIgnoreCase)-ge 0 -and $$c.IndexOf(''course_navigator'',[StringComparison]::OrdinalIgnoreCase)-ge 0)){$$m=$$true;break}};$$m}}|%{$$target=$$_.ProcessId;Stop-Process -Id $$target -Force -ErrorAction SilentlyContinue;Wait-Process -Id $$target -Timeout 5 -ErrorAction SilentlyContinue}"'
  Sleep 1000
  ; Bundled resources are replaced as a whole, so files a release no longer
  ; ships (such as the former portable Node.js) do not linger after upgrades.
  DetailPrint "Removing previous bundled runtime resources..."
  RMDir /r "$INSTDIR\runtime-source"
  RMDir /r "$INSTDIR\runtime-tools"
!macroend
