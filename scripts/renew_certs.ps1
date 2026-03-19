param(
    [string]$OpenSslExe = "openssl",
    [string]$OutDir = "cert"
)

New-Item -Path $OutDir -ItemType Directory -Force | Out-Null
$certPath = Join-Path $OutDir "localhost-renewed.pem"
$keyPath = Join-Path $OutDir "localhost-renewed-key.pem"
$subj = "/C=KR/ST=Seoul/L=Seoul/O=CleverSearch/OU=Dev/CN=localhost"

& $OpenSslExe req -x509 -nodes -days 365 -newkey rsa:2048 -keyout $keyPath -out $certPath -subj $subj
if ($LASTEXITCODE -ne 0) {
    throw "인증서 갱신 실패"
}
Write-Output "인증서 생성 완료: $certPath"
