Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
repoRoot = fso.GetParentFolderName(scriptDir)
configPath = fso.BuildPath(fso.BuildPath(repoRoot, "data"), "windows-hub-url.txt")

shell.CurrentDirectory = repoRoot

If fso.FileExists(configPath) Then
    Set configFile = fso.OpenTextFile(configPath, 1, False)
    hubUrl = Trim(configFile.ReadAll)
    configFile.Close
    If Len(hubUrl) > 0 Then
        shell.Run "cmd.exe /c start """" """ & hubUrl & """", 0, False
        WScript.Quit 0
    End If
End If

psScript = fso.BuildPath(scriptDir, "EthroxDetect.Windows.ps1")
command = "powershell.exe -STA -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File """ & psScript & """"
shell.Run command, 1, False
