param([long]$WindowHandle, [int]$ProcessId)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
try {
    $root = [System.Windows.Automation.AutomationElement]::FromHandle([IntPtr]::new($WindowHandle))
    if ($null -eq $root -or $root.Current.ProcessId -ne $ProcessId) { throw 'Window changed' }
    $walker = [System.Windows.Automation.TreeWalker]::ControlViewWalker
    $queue = [System.Collections.Generic.Queue[System.Windows.Automation.AutomationElement]]::new()
    $queue.Enqueue($root)
    $controls = [System.Collections.Generic.List[object]]::new()
    $visited = 0
    $characters = 0
    $allowed = @('Text', 'Button', 'CheckBox', 'RadioButton', 'MenuItem', 'TabItem', 'Hyperlink', 'ListItem', 'ComboBox', 'Window', 'Group')
    while ($queue.Count -gt 0 -and $visited -lt 200 -and $characters -lt 10000) {
        $element = $queue.Dequeue()
        $visited++
        $info = $element.Current
        if ($info.IsPassword -or $info.IsOffscreen -or $info.ProcessId -ne $ProcessId) { continue }
        $type = $info.ControlType.ProgrammaticName.Replace('ControlType.', '')
        # Read visible labels only; no ValuePattern, keystrokes or InvokePattern.
        $name = $info.Name
        if ($allowed -contains $type -and -not [string]::IsNullOrWhiteSpace($name)) {
            if ($name.Length -gt 500) { $name = $name.Substring(0, 500) }
            $characters += $name.Length
            $entry = @{type=$type;name=$name;enabled=$info.IsEnabled}
            # Read state only, never values or invoke methods. Password nodes were excluded above.
            $pattern = $null
            if ($element.TryGetCurrentPattern([System.Windows.Automation.TogglePattern]::Pattern, [ref]$pattern)) {
                $entry.checked = $pattern.Current.ToggleState.ToString().ToLowerInvariant()
            }
            $pattern = $null
            if ($element.TryGetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern, [ref]$pattern)) {
                $entry.selected = $pattern.Current.IsSelected
            }
            $controls.Add($entry)
        }
        $child = $walker.GetFirstChild($element)
        while ($null -ne $child -and $queue.Count -lt 200) {
            $queue.Enqueue($child)
            $child = $walker.GetNextSibling($child)
        }
    }
    if ($root.Current.ProcessId -ne $ProcessId) { throw 'Window changed' }
    @{status='read';controls=@($controls.ToArray());truncated=($queue.Count -gt 0)} | ConvertTo-Json -Depth 4 -Compress
} catch {
    @{status='unsupported';controls=@()} | ConvertTo-Json -Compress
}
