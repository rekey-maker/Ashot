# Ashot GDI+ vector renderer. ASCII-only on purpose: PowerShell 5.1 reads
# BOM-less .ps1 as ANSI/GBK, and multi-byte UTF-8 comments can misalign
# line ends and swallow the param() line (real bug caught in v0.1.7).
# All geometry is precomputed by Python (vector.py); this script only
# draws exactly what it is told, with anti-aliasing on.
param($SpecPath)
$ErrorActionPreference = 'Stop'
$spec = Get-Content $SpecPath -Raw -Encoding UTF8 | ConvertFrom-Json
Add-Type -AssemblyName System.Drawing
$src = [System.Drawing.Image]::FromFile($spec.'in')
$bmp = New-Object System.Drawing.Bitmap($src.Width, $src.Height)
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
$g.TextRenderingHint = [System.Drawing.Text.TextRenderingHint]::AntiAliasGridFit
$g.DrawImage($src, 0, 0, $src.Width, $src.Height)
foreach ($s in $spec.shapes) {
    $col = [System.Drawing.ColorTranslator]::FromHtml($s.color)
    if ($s.t -eq 'stroke') {
        $pen = New-Object System.Drawing.Pen($col, [float]$s.width)
        $pen.StartCap = [System.Drawing.Drawing2D.LineCap]::Round
        $pen.EndCap = [System.Drawing.Drawing2D.LineCap]::Round
        $pen.LineJoin = [System.Drawing.Drawing2D.LineJoin]::Round
        $pts = New-Object 'System.Drawing.PointF[]' ($s.pts.Count)
        for ($i = 0; $i -lt $s.pts.Count; $i++) {
            $pts[$i] = New-Object System.Drawing.PointF(
                [float]$s.pts[$i][0], [float]$s.pts[$i][1])
        }
        $g.DrawLines($pen, $pts)
        $pen.Dispose()
    }
    elseif ($s.t -eq 'fill') {
        $brush = New-Object System.Drawing.SolidBrush($col)
        $pts = New-Object 'System.Drawing.PointF[]' ($s.pts.Count)
        for ($i = 0; $i -lt $s.pts.Count; $i++) {
            $pts[$i] = New-Object System.Drawing.PointF(
                [float]$s.pts[$i][0], [float]$s.pts[$i][1])
        }
        $g.FillPolygon($brush, $pts)
        $brush.Dispose()
    }
    elseif ($s.t -eq 'dot') {
        $brush = New-Object System.Drawing.SolidBrush($col)
        $g.FillEllipse($brush, [float]($s.cx - $s.r), [float]($s.cy - $s.r),
                       [float](2 * $s.r), [float](2 * $s.r))
        $wfont = New-Object System.Drawing.Font(
            [string]$s.font, [float]($s.r * 1.15),
            [System.Drawing.FontStyle]::Bold,
            [System.Drawing.GraphicsUnit]::Pixel)
        $wb = [System.Drawing.Brushes]::White
        $msz = $g.MeasureString($s.label, $wfont)
        $g.DrawString($s.label, $wfont, $wb,
                      [float]($s.cx - $msz.Width / 2),
                      [float]($s.cy - $msz.Height / 2))
        $brush.Dispose(); $wfont.Dispose()
    }
    elseif ($s.t -eq 'text') {
        $brush = New-Object System.Drawing.SolidBrush($col)
        # v0.1.9: font family + bold come from the op (defaults filled by
        # vector.py); unknown family names fall back silently inside GDI+
        $style = [System.Drawing.FontStyle]::Bold
        if ($s.bold -eq $false) { $style = [System.Drawing.FontStyle]::Regular }
        $font = New-Object System.Drawing.Font(
            [string]$s.font, [float]$s.size, $style,
            [System.Drawing.GraphicsUnit]::Pixel)
        $g.DrawString($s.s, $font, $brush, [float]$s.x, [float]$s.y)
        $brush.Dispose(); $font.Dispose()
    }
}
$g.Dispose()
$bmp.Save($spec.'out', [System.Drawing.Imaging.ImageFormat]::Png)
$bmp.Dispose()
$src.Dispose()
Write-Output 'OK'
