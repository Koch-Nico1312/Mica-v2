param([long]$WindowHandle, [int]$ProcessId)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
try {
    $element = [System.Windows.Automation.AutomationElement]::FocusedElement
    if ($null -eq $element -or $element.Current.ProcessId -ne $ProcessId) {
        @{status='changed'} | ConvertTo-Json -Compress
        exit 0
    }
    if ($element.Current.IsPassword) {
        @{status='password'} | ConvertTo-Json -Compress
        exit 0
    }
    $pattern = $null
    if ($element.TryGetCurrentPattern([System.Windows.Automation.TextPattern]::Pattern, [ref]$pattern)) {
        $parts = @($pattern.GetSelection() | ForEach-Object { $_.GetText(16001) })
        $text = $parts -join "`n"
        if ($text.Length -gt 16000) {
            @{status='too_large'} | ConvertTo-Json -Compress
        } elseif ($text.Trim().Length -gt 0) {
            @{status='selected';text=$text} | ConvertTo-Json -Compress
        } else {
            @{status='empty'} | ConvertTo-Json -Compress
        }
    } else {
        @{status='unsupported'} | ConvertTo-Json -Compress
    }
} catch {
    @{status='unsupported'} | ConvertTo-Json -Compress
}
