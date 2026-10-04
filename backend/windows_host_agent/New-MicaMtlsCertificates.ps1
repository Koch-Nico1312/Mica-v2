[CmdletBinding()]
param(
    [string]$OutputDirectory = "$env:ProgramData\Mica\tls",
    [string]$OpenSslPath = ""
)

$ErrorActionPreference = "Stop"
if (Test-Path variable:PSNativeCommandUseErrorActionPreference) {
    $PSNativeCommandUseErrorActionPreference = $true
}

if (-not $OpenSslPath) {
    $candidates = @(
        (Get-Command openssl -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -First 1),
        "C:\Program Files\Git\usr\bin\openssl.exe",
        "C:\Program Files\Git\mingw64\bin\openssl.exe"
    ) | Where-Object { $_ -and (Test-Path -LiteralPath $_) }
    $OpenSslPath = $candidates | Select-Object -First 1
}
if (-not $OpenSslPath -or -not (Test-Path -LiteralPath $OpenSslPath)) {
    throw "OpenSSL was not found. Install it or pass -OpenSslPath explicitly."
}

$destination = [System.IO.Path]::GetFullPath($OutputDirectory)
$expected = @("broker-ca.crt", "broker-ca.key", "host.crt", "host.key", "client.crt", "client.key")
foreach ($name in $expected) {
    if (Test-Path -LiteralPath (Join-Path $destination $name)) {
        throw "Refusing to overwrite existing TLS material in $destination"
    }
}
New-Item -ItemType Directory -Path $destination -Force | Out-Null

$caKey = Join-Path $destination "broker-ca.key"
$caCrt = Join-Path $destination "broker-ca.crt"
$hostKey = Join-Path $destination "host.key"
$hostCsr = Join-Path $destination "host.csr"
$hostCrt = Join-Path $destination "host.crt"
$clientKey = Join-Path $destination "client.key"
$clientCsr = Join-Path $destination "client.csr"
$clientCrt = Join-Path $destination "client.crt"
$hostExt = Join-Path $destination "host.ext"
$clientExt = Join-Path $destination "client.ext"

& $OpenSslPath genrsa -out $caKey 3072
& $OpenSslPath req -x509 -new -sha256 -key $caKey -days 3650 -out $caCrt -subj "/CN=MICA Phase 0 Broker CA" `
    -addext "basicConstraints=critical,CA:TRUE,pathlen:0" `
    -addext "keyUsage=critical,keyCertSign,cRLSign" `
    -addext "subjectKeyIdentifier=hash"
& $OpenSslPath genrsa -out $hostKey 3072
& $OpenSslPath req -new -sha256 -key $hostKey -out $hostCsr -subj "/CN=host.docker.internal"
Set-Content -LiteralPath $hostExt -Encoding ascii -Value @(
    "basicConstraints=CA:FALSE",
    "keyUsage=digitalSignature,keyEncipherment",
    "extendedKeyUsage=serverAuth",
    "subjectKeyIdentifier=hash",
    "authorityKeyIdentifier=keyid,issuer",
    "subjectAltName=DNS:host.docker.internal,DNS:mica-host.local,IP:127.0.0.1"
)
& $OpenSslPath x509 -req -sha256 -in $hostCsr -CA $caCrt -CAkey $caKey -CAcreateserial -out $hostCrt -days 825 -extfile $hostExt
& $OpenSslPath genrsa -out $clientKey 3072
& $OpenSslPath req -new -sha256 -key $clientKey -out $clientCsr -subj "/CN=mica-tool-broker"
Set-Content -LiteralPath $clientExt -Encoding ascii -Value @(
    "basicConstraints=CA:FALSE",
    "keyUsage=digitalSignature,keyEncipherment",
    "extendedKeyUsage=clientAuth",
    "subjectKeyIdentifier=hash",
    "authorityKeyIdentifier=keyid,issuer"
)
& $OpenSslPath x509 -req -sha256 -in $clientCsr -CA $caCrt -CAkey $caKey -CAcreateserial -out $clientCrt -days 365 -extfile $clientExt

Remove-Item -LiteralPath $hostCsr, $clientCsr, $hostExt, $clientExt -Force
$serial = Join-Path $destination "broker-ca.srl"
if (Test-Path -LiteralPath $serial) { Remove-Item -LiteralPath $serial -Force }

& icacls.exe $destination /inheritance:r /grant:r "${env:USERNAME}:(OI)(CI)F" /grant:r "SYSTEM:(OI)(CI)F" | Out-Null
if ($LASTEXITCODE -ne 0) { throw "TLS files were generated but their Windows ACL could not be restricted." }

Write-Output "Generated a server certificate for host.docker.internal and a client certificate for CN=mica-tool-broker."
Write-Output "Keep broker-ca.key offline after initial setup. Copy broker-ca.crt, client.crt and client.key to the broker's read-only host-agent-client directory."
