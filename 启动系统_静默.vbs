Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
root = fso.GetParentFolderName(WScript.ScriptFullName)

For Each file In fso.GetFolder(root).Files
    If LCase(fso.GetExtensionName(file.Name)) = "bat" Then
        shell.Run Chr(34) & file.Path & Chr(34), 0, False
        Exit For
    End If
Next
