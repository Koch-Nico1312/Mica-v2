param(
    [int]$Port = 9443
)

$ErrorActionPreference = 'Stop'
$profiles = Get-NetFirewallProfile -PolicyStore ActiveStore
if ($profiles | Where-Object { $_.DefaultInboundAction -ne 'Block' }) {
    throw 'All active Windows Firewall profiles must use DefaultInboundAction=Block.'
}

$ruleNames = @(
    'MICA Windows Host Agent block LAN TCP',
    'MICA Windows Host Agent block LAN UDP'
)
foreach ($ruleName in $ruleNames) {
    if (Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue) {
        throw "Firewall rule already exists. Review it manually before replacing: $ruleName"
    }
}

# Caddy is separately required to bind 127.0.0.1 only. Docker Desktop's
# host.docker.internal loopback proxy remains reachable, while these explicit
# rules add defence in depth if a future configuration accidentally creates a
# LAN listener. Windows loopback traffic is not admitted by an Allow rule here.
New-NetFirewallRule `
    -DisplayName $ruleNames[0] `
    -Direction Inbound `
    -Action Block `
    -Protocol TCP `
    -LocalPort $Port `
    -Profile Any

New-NetFirewallRule `
    -DisplayName $ruleNames[1] `
    -Direction Inbound `
    -Action Block `
    -Protocol UDP `
    -LocalPort $Port `
    -Profile Any

foreach ($ruleName in $ruleNames) {
    Get-NetFirewallRule -DisplayName $ruleName | Format-List DisplayName, Enabled, Direction, Action, Profile
    Get-NetFirewallRule -DisplayName $ruleName | Get-NetFirewallPortFilter
}
