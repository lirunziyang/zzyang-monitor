' 子漾监测 —— 无控制台窗口启动
Option Explicit
Dim sh, fso, here
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
here = fso.GetParentFolderName(WScript.ScriptFullName)
sh.CurrentDirectory = here
sh.Run """" & here & "\runtime\pythonw.exe"" """ & here & "\app.py""", 0, False
