Set fso = CreateObject("Scripting.FileSystemObject")
exe = "C:\Users\chugs\AppData\Local\Programs\Python\Python315\pythonw.exe"
If Not fso.FileExists(exe) Then
  MsgBox "pythonw.exe not found at:" & vbCrLf & exe, 16, "MalO"
  WScript.Quit 1
End If
Set sh = CreateObject("WScript.Shell")
sh.CurrentDirectory = "C:\Users\chugs\Documents\Mal0_V1.0.2"
sh.Run """" & exe & """ -m supervise", 0, False