# Ashot image transform (crop / scale / PNG-JPEG encode) via GDI+.
# ASCII-only on purpose: PowerShell 5.1 reads BOM-less .ps1 as ANSI/GBK and
# multi-byte UTF-8 comments can swallow the param() line (same real bug that
# hit _gdi_render.ps1 in v0.1.7).
#
# Spec JSON (all paths are absolute; non-ASCII is \u-escaped by Python):
#   {"in":path, "out":path, "crop":[x,y,w,h]|null, "size":[w,h]|null,
#    "format":"png"|"jpeg", "quality":85}
# Crop box is already clamped/validated by Python (transform.py); this script
# performs exactly what it is told and reports the real output size:
#   last stdout line = {"ok":true,"w":..,"h":..,"bytes":..}
param($SpecPath)
$ErrorActionPreference = 'Stop'
$spec = Get-Content $SpecPath -Raw -Encoding UTF8 | ConvertFrom-Json
Add-Type -AssemblyName System.Drawing

$src = [System.Drawing.Image]::FromFile($spec.'in')
$img = $src
if ($null -ne $spec.crop) {
    $rc = [System.Drawing.Rectangle]::new(
        [int]$spec.crop[0], [int]$spec.crop[1],
        [int]$spec.crop[2], [int]$spec.crop[3])
    $img = $src.Clone($rc, $src.PixelFormat)
}

if ($spec.format -eq 'jpeg') {
    # JPEG has no alpha channel: draw onto 24bpp so the encoder never has to
    # guess (screenshots are opaque, but clipped PNGs may carry alpha).
    $pf = [System.Drawing.Imaging.PixelFormat]::Format24bppRgb
} else {
    $pf = [System.Drawing.Imaging.PixelFormat]::Format32bppArgb
}
if ($null -ne $spec.size) {
    $dw = [int]$spec.size[0]
    $dh = [int]$spec.size[1]
} else {
    $dw = [int]$img.Width
    $dh = [int]$img.Height
}
$bmp = New-Object System.Drawing.Bitmap($dw, $dh, $pf)
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.CompositingQuality = [System.Drawing.Drawing2D.CompositingQuality]::HighQuality
$g.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
$g.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality
$g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::HighQuality
$g.DrawImage($img, 0, 0, $dw, $dh)
$g.Dispose()

if ($spec.format -eq 'jpeg') {
    $codec = [System.Drawing.Imaging.ImageCodecInfo]::GetImageEncoders() |
             Where-Object { $_.MimeType -eq 'image/jpeg' }
    $ep = New-Object System.Drawing.Imaging.EncoderParameters(1)
    $ep.Param[0] = New-Object System.Drawing.Imaging.EncoderParameter(
        [System.Drawing.Imaging.Encoder]::Quality, [long]$spec.quality)
    $bmp.Save($spec.'out', $codec, $ep)
    $ep.Dispose()
} else {
    $bmp.Save($spec.'out', [System.Drawing.Imaging.ImageFormat]::Png)
}
$w = $bmp.Width
$h = $bmp.Height
$bmp.Dispose()
if (-not [object]::ReferenceEquals($img, $src)) { $img.Dispose() }
$src.Dispose()
$len = (Get-Item -LiteralPath $spec.'out').Length
Write-Output ([pscustomobject]@{ ok = $true; w = $w; h = $h; bytes = $len } |
              ConvertTo-Json -Compress)
