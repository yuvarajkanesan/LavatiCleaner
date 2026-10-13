<#
  Creates a SELF-SIGNED code-signing certificate for testing the signing pipeline.
  It is NOT trusted by other PCs and does NOT remove SmartScreen warnings; real releases need a certificate
  from a public CA (OV/EV) or Azure Trusted Signing. This script does not install the certificate into any
  trust store; it only puts it in your personal store. Remove it with:  tools\make_test_cert.ps1 -Remove
#>
param([switch]$Remove)
$subject = "CN=Lavati Softwares (TEST - self-signed)"
if ($Remove) {
    Get-ChildItem Cert:\CurrentUser\My | Where-Object Subject -eq $subject | Remove-Item
    Write-Host "Removed test certificates."; exit 0
}
$c = New-SelfSignedCertificate -Type CodeSigningCert -Subject $subject -CertStoreLocation Cert:\CurrentUser\My `
        -HashAlgorithm SHA256 -KeyExportPolicy NonExportable -NotAfter (Get-Date).AddYears(1)
Write-Host "Thumbprint: $($c.Thumbprint)"
Write-Host "Use it:  set SIGN_CERT_SHA1=$($c.Thumbprint)   (then run build.bat)"
