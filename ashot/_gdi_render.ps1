# Ashot GDI+ vector renderer. ASCII-only on purpose: PowerShell 5.1 reads
# BOM-less .ps1 as ANSI/GBK, and multi-byte UTF-8 comments can misalign
# line ends and swallow the param() line (real bug caught in v0.1.7).
# All geometry is precomputed by Python (vector.py); this script only
# draws exactly what it is told, with anti-aliasing on.
#
# v0.2.6: text ops may carry w>0 -> DrawString(RectangleF) native word wrap
# (GDI+ measures real font metrics; we do NOT guess char widths in Python).
# Every text/dot op is measured with MeasureString and reported back as JSON
# on the last stdout line: {"ok":true,"boxes":[{"i":op,"x":..,"y":..,"w":..,"h":..}]}
# Python compares those boxes with the canvas and emits bounds_warn.
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
$boxes = @()
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
        $boxes += [pscustomobject]@{
            i = [int]$s.i
            x = [Math]::Round([double]($s.cx - $msz.Width / 2), 2)
            y = [Math]::Round([double]($s.cy - $msz.Height / 2), 2)
            w = [Math]::Round([double]$msz.Width, 2)
            h = [Math]::Round([double]$msz.Height, 2)
        }
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
        $lw = [double]$s.w
        if ($lw -gt 0) {
            # Native wrap: GDI+ lays out inside the rectangle using real
            # font metrics (design v0.2.6 / Q15). h<=0 -> no vertical limit.
            $lh = [double]$s.h
            if ($lh -le 0) { $lh = 100000.0 }
            $layout = New-Object System.Drawing.RectangleF(
                [float]$s.x, [float]$s.y, [float]$lw, [float]$lh)
            $msz = $g.MeasureString($s.s, $font, [int][Math]::Max(1, [int]$lw))
            $g.DrawString($s.s, $font, $brush, $layout)
        }
        else {
            $msz = $g.MeasureString($s.s, $font)
            $g.DrawString($s.s, $font, $brush, [float]$s.x, [float]$s.y)
        }
        $boxes += [pscustomobject]@{
            i = [int]$s.i
            x = [Math]::Round([double]$s.x, 2)
            y = [Math]::Round([double]$s.y, 2)
            w = [Math]::Round([double]$msz.Width, 2)
            h = [Math]::Round([double]$msz.Height, 2)
        }
        $brush.Dispose(); $font.Dispose()
    }
}
$g.Dispose()
$bmp.Save($spec.'out', [System.Drawing.Imaging.ImageFormat]::Png)
$bmp.Dispose()
$src.Dispose()
$report = [pscustomobject]@{ ok = $true; boxes = @($boxes) }
Write-Output ($report | ConvertTo-Json -Compress -Depth 5)
