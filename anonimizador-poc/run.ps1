# Equivalente ao Makefile para Windows sem `make`.
#   .\run.ps1 build
#   .\run.ps1 corpus
#   .\run.ps1 eval
param(
    [Parameter(Position = 0)]
    [ValidateSet('build','test','test-all','corpus','eval','eval-fast','offline-proof',
                 'demo','shell','gpu-build','gpu-eval','clean','help')]
    [string]$Target = 'help'
)

$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

$gpu = @('-f','docker-compose.yml','-f','docker-compose.gpu.yml')

switch ($Target) {
    'build'         { docker compose build }
    'test'          { docker compose run --rm test -q -m "not slow" }
    'test-all'      { docker compose run --rm test -q }
    'corpus'        { docker compose run --rm corpus }
    'eval'          { docker compose run --rm eval }
    'eval-fast'     { docker compose run --rm cli eval --ner spacy }
    'offline-proof' { docker compose run --rm offline-proof }
    'demo'          {
        docker compose run --rm cli redact `
            --in /app/eval/datasets/contrato-000.pdf `
            --out /app/out/contrato-000.redigido.pdf
    }
    'shell'         { docker compose run --rm dev }
    'gpu-build'     { docker compose @gpu build }
    'gpu-eval'      { docker compose @gpu run --rm eval }
    'clean'         {
        foreach ($p in @('out','eval\datasets')) {
            if (Test-Path $p) { Get-ChildItem $p -Force | Remove-Item -Recurse -Force }
        }
        if (Test-Path 'eval\report.md') { Remove-Item 'eval\report.md' -Force }
        Write-Host 'saidas removidas'
    }
    default {
        Write-Host ''
        Write-Host '  build          constroi a imagem (unica etapa com rede)'
        Write-Host '  test           testes rapidos (sem carregar modelos)'
        Write-Host '  test-all       todos os testes, inclusive os marcados slow'
        Write-Host '  corpus         gera 50 PDFs sinteticos + gabarito'
        Write-Host '  eval           avaliacao completa nas 3 configuracoes de NER'
        Write-Host '  eval-fast      avaliacao so com spaCy (iteracao rapida)'
        Write-Host '  offline-proof  prova que o pipeline roda sem rede'
        Write-Host '  demo           redige um documento do corpus'
        Write-Host '  shell          shell interativo no container'
        Write-Host '  gpu-build      constroi a imagem com torch CUDA'
        Write-Host '  gpu-eval       avaliacao usando GPU'
        Write-Host '  clean          remove saidas geradas'
        Write-Host ''
    }
}
