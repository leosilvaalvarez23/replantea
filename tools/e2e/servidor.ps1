param([string]$Root,[int]$Port=8768)
# Servidor estático para el arnés E2E: /app/*, /comprador/<token> y /src/*; inyecta el desvío de fetch hacia el arnés (iframe).
$types=@{'.html'='text/html; charset=utf-8';'.png'='image/png';'.js'='text/javascript';'.css'='text/css';'.svg'='image/svg+xml';'.py'='text/plain; charset=utf-8'}
$shim='<script>if(window.parent&&window.parent!==window&&window.parent.__apiShim){const o=window.fetch.bind(window);window.fetch=(u,p)=>String(u).startsWith("/api/")?window.parent.__apiShim(u,p):o(u,p)}</script>'
$l=New-Object System.Net.HttpListener
$l.Prefixes.Add("http://localhost:$Port/")
$l.Start()
while($l.IsListening){
  $c=$l.GetContext()
  $rel=[Uri]::UnescapeDataString($c.Request.Url.AbsolutePath.TrimStart('/'))
  if($rel -like 'comprador/*'){ $rel='app/comprador.html' }
  $p=[IO.Path]::GetFullPath((Join-Path $Root $rel))
  if($p.StartsWith($Root) -and (Test-Path $p -PathType Leaf)){
    $e=[IO.Path]::GetExtension($p).ToLower()
    $c.Response.ContentType=$(if($types.ContainsKey($e)){$types[$e]}else{'application/octet-stream'})
    if($e -eq '.html' -and $rel -notin @('e2e.html','unit.html')){
      $t=[IO.File]::ReadAllText($p,[Text.Encoding]::UTF8) -replace '<head>',('<head>'+$shim)
      $b=[Text.Encoding]::UTF8.GetBytes($t)
    } else { $b=[IO.File]::ReadAllBytes($p) }
    $c.Response.Headers.Add('Cache-Control','no-store')
    $c.Response.OutputStream.Write($b,0,$b.Length)
  } else { $c.Response.StatusCode=404 }
  $c.Response.Close()
}
