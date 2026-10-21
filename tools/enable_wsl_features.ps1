#Requires -RunAsAdministrator
[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$EvidenceDirectory)
$ErrorActionPreference = 'Stop'
$destination = [System.IO.Path]::GetFullPath($EvidenceDirectory)
if (Test-Path -LiteralPath $destination) { throw 'Use a new evidence directory; previous evidence is preserved.' }
New-Item -ItemType Directory -Path $destination | Out-Null
$records = @()
$mustRestart = $false
foreach ($feature in @('Microsoft-Windows-Subsystem-Linux', 'VirtualMachinePlatform')) {
    $before = Get-WindowsOptionalFeature -Online -FeatureName $feature
    $record = [ordered]@{feature=$feature;before=$before.State.ToString();after=$null;restartNeeded=$false;status='not_attempted'}
    try {
        if ($before.State.ToString() -eq 'EnablePending') {
            $record.status = 'already_pending_restart'
            $record.restartNeeded = $true
        } elseif ($before.State.ToString() -eq 'Enabled') {
            $record.status = 'already_enabled'
        } elseif ($before.State.ToString() -eq 'Disabled') {
            $result = Enable-WindowsOptionalFeature -Online -FeatureName $feature -All -NoRestart
            $record.restartNeeded = [bool]$result.RestartNeeded
            $record.status = 'enable_requested'
        } else {
            throw ('Unexpected feature state: ' + $before.State)
        }
        $record.after = (Get-WindowsOptionalFeature -Online -FeatureName $feature).State.ToString()
        if ($record.after -eq 'EnablePending') { $record.restartNeeded = $true }
        $mustRestart = $mustRestart -or $record.restartNeeded
    } catch {
        $record.status = 'failed'
        $record['error'] = $_.Exception.Message
        $records += [pscustomobject]$record
        $records | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $destination 'features.json') -Encoding utf8
        throw
    }
    $records += [pscustomobject]$record
    $records | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $destination 'features.json') -Encoding utf8
}
[ordered]@{checkedAt=(Get-Date -Format o);restartNeeded=$mustRestart;automaticRestartPerformed=$false;features=$records} |
    ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $destination 'result.json') -Encoding utf8
Write-Output ('Feature configuration finished. Manual restart required: ' + $mustRestart)
# Deliberately no Restart-Computer, shutdown, distro install or Git operations.
