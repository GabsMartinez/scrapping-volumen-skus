<#
correr.ps1 - atajos para Windows (PowerShell). Todo corre dentro de Docker.

  .\scripts\correr.ps1 levantar      construye y levanta Postgres + scraper
  .\scripts\correr.ps1 excel         genera salidas\excel\reporte_scraper_precios.xlsx
  .\scripts\correr.ps1 estado        conteos de la base
  .\scripts\correr.ps1 respaldar     guarda la base actual en db\datos\datos.sql
  .\scripts\correr.ps1 psql          consola SQL de la base
  .\scripts\correr.ps1 bajar         apaga los contenedores (los datos se quedan)
  .\scripts\correr.ps1 <otro>        cualquier comando de main.py:
                                     match tyco, crawl mech, enriquecer --forzar, listar...

Si PowerShell no deja correr scripts:
  powershell -ExecutionPolicy Bypass -File .\scripts\correr.ps1 excel
#>
param(
    [Parameter(Position = 0)][string]$Comando = "ayuda",
    [Parameter(ValueFromRemainingArguments = $true)][string[]]$Resto
)

$Raiz = Split-Path -Parent $PSScriptRoot
$Usuario = if ($env:DB_USER) { $env:DB_USER } else { "scraper" }
$Base = if ($env:DB_NAME) { $env:DB_NAME } else { "scraper_precios" }

function Revisar([string]$Paso) {
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[ERROR] fallo en: $Paso (codigo $LASTEXITCODE)" -ForegroundColor Red
        Pop-Location
        exit $LASTEXITCODE
    }
}

Push-Location $Raiz
switch ($Comando) {
    "ayuda" {
        Get-Content $PSCommandPath | Select-Object -Skip 1 -First 13
    }
    "levantar" {
        docker compose up -d --build; Revisar "docker compose up"
        docker compose exec -T scraper python main.py estado; Revisar "estado"
    }
    "bajar" {
        docker compose down; Revisar "docker compose down"
    }
    "respaldar" {
        docker compose exec -T postgres pg_dump -U $Usuario -d $Base --data-only --column-inserts --no-owner --no-privileges -f /tmp/datos.sql
        Revisar "pg_dump"
        docker compose cp postgres:/tmp/datos.sql db/datos/datos.sql; Revisar "copiar dump"
        docker compose exec -T scraper python -m db.limpiar_dump db/datos/datos.sql; Revisar "limpiar dump"
        Write-Host "Respaldo listo: db\datos\datos.sql (haz commit para guardarlo en el repo)"
    }
    "psql" {
        docker compose exec postgres psql -U $Usuario -d $Base
    }
    default {
        docker compose exec -T scraper python main.py $Comando @Resto; Revisar "main.py $Comando"
    }
}
Pop-Location
