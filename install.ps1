# Установка Normal Black Row: программа и модель апскейлера.
$ErrorActionPreference = "Stop"

$default = Join-Path $env:USERPROFILE "NormalBlackRow"
Write-Host "Normal Black Row"
Write-Host "Путь лучше без кириллицы, например $default"
$dest = Read-Host "Куда установить (Enter — $default)"
if ([string]::IsNullOrWhiteSpace($dest)) {
    $dest = $default
}

New-Item -ItemType Directory -Force -Path $dest | Out-Null

$zip = Join-Path $env:TEMP "NormalBlackRow-master.zip"
$unpack = Join-Path $env:TEMP "NormalBlackRow-unpack"
Write-Host "Скачиваю программу и модель..."
Invoke-WebRequest -Uri "https://github.com/mercutov/NormalBlackRow/archive/refs/heads/master.zip" -OutFile $zip -UseBasicParsing
if (Test-Path $unpack) {
    Remove-Item $unpack -Recurse -Force
}
Expand-Archive -Path $zip -DestinationPath $unpack -Force
$source = Get-ChildItem $unpack -Directory | Select-Object -First 1
Copy-Item -Path (Join-Path $source.FullName "*") -Destination $dest -Recurse -Force

Write-Host "Ставлю Pillow..."
py -3 -m pip install -r (Join-Path $dest "requirements.txt")

Write-Host ""
Write-Host "Готово. Запуск: $dest\Normal Black Row.bat"
Write-Host "При следующем запуске программа сама проверит обновления."
