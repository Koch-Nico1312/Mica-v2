param([long]$WindowHandle, [int]$ProcessId, [string]$TimerId)
$ErrorActionPreference = 'Stop'
if ($TimerId -notmatch '^[a-f0-9]{32}$') { throw 'Invalid test timer id' }
$process = Get-CimInstance Win32_Process -Filter "ProcessId = $ProcessId"
if (-not $process -or $process.CommandLine -notmatch [regex]::Escape($TimerId) -or $process.CommandLine -notmatch 'desktop.core.timer_delivery') { throw 'Not the test worker' }
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
$window = [System.Windows.Automation.AutomationElement]::FromHandle([IntPtr]$WindowHandle)
$expectedTitle = 'MICA ' + [char]183 + ' Timer'
if ($window.Current.ProcessId -ne $ProcessId -or $window.Current.Name -ne $expectedTitle) { throw 'Unexpected test window' }
$buttonName = '10 Minuten sp' + [char]228 + 'ter'
$condition = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::NameProperty, $buttonName)
$button = $window.FindFirst([System.Windows.Automation.TreeScope]::Descendants, $condition)
if (-not $button -or $button.Current.ControlType -ne [System.Windows.Automation.ControlType]::Button) { throw 'No snooze button' }
$pattern = $button.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern)
$pattern.Invoke()
Write-Output 'snooze invoked'
