# Equivalente ao Makefile para Windows sem `make`.
#   .\run.ps1 build
#   .\run.ps1 corpus
#   .\run.ps1 eval
param(
    [Parameter(Position = 0)]
    [ValidateSet('build','test','test-all','corpus','eval','eval-fast','diagnostico','gate-usabilidade','gate-usabilidade-apurar','ui','ui-recarregar','ui-down','ui-proof','ui-llm','llm-proof','offline-proof',
                 'demo','shell','usuario','tunel','gpu-build','gpu-eval','clean','help')]
    [string]$Target = 'help',

    # Para o alvo `usuario`.
    [string]$Email,
    [string]$Inquilino,
    [ValidateSet('operador','dono','plataforma')]
    [string]$Papel = 'dono',

    # Aceita tambem a sintaxe do Makefile (EMAIL=... INQUILINO=...), porque o
    # README e o docs/04 mostram `make usuario` e ninguem deveria ter que
    # lembrar qual das duas formas serve para qual sistema.
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Resto
)

foreach ($arg in $Resto) {
    if ($arg -match '^(?<k>[A-Za-z_]+)=(?<v>.*)$') {
        switch ($Matches['k'].ToUpper()) {
            'EMAIL'     { $Email = $Matches['v'] }
            'INQUILINO' { $Inquilino = $Matches['v'] }
            'PAPEL'     { $Papel = $Matches['v'] }
        }
    }
}

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
    'diagnostico'   { docker compose run --rm diagnostico }
    'gate-usabilidade' { docker compose run --rm gate-usabilidade }
    'gate-usabilidade-apurar' { docker compose run --rm gate-usabilidade --apurar /app/eval/gate-usabilidade/registro.csv }
    'ui'            {
        docker compose up -d ui ui-proxy
        Write-Host 'aguardando a UI subir (o modelo leva ~30 s)...'
        $ok = $false
        foreach ($i in 1..90) {
            try {
                Invoke-RestMethod -Uri 'http://127.0.0.1:8000/api/saude' -TimeoutSec 3 | Out-Null
                $ok = $true; break
            } catch { Start-Sleep -Seconds 2 }
        }
        Write-Host ''
        if ($ok) {
            # Dizer o modo a cada subida: o servico sobe igual nos dois, e
            # descobrir por acidente que esta aberto e tarde.
            docker compose exec -T ui python -m anonimizador.web.modo
        } else {
            Write-Host '  a UI ainda nao respondeu; acompanhe com:'
            Write-Host '    docker compose logs -f ui'
        }
        Write-Host '  interface em http://127.0.0.1:8000'
        Write-Host ''
    }
    'ui-recarregar' {
        # Um comando depois de QUALQUER alteracao, sem decidir nada. A regra
        # de o que exige reiniciar nao deveria ser trabalho de quem usa:
        #   .env / docker-compose.yml  -> `up -d` ja recria
        #   codigo Python              -> precisa recriar (uvicorn sem reload)
        #   CSS / JS / HTML            -> nada; basta recarregar a pagina
        #
        # Recria APENAS o `ui`. O `ui-proxy` fica de pe: e ele que segura a
        # porta publicada, e recria-lo derrubaria um tunel do cloudflared
        # apontado para 127.0.0.1:8000 — a URL que voce ja mandou para
        # alguem. O proxy resolve `ui` por DNS a cada conexao, entao acha o
        # container novo sozinho.
        docker compose up -d ui-proxy
        docker compose up -d --force-recreate ui
        Write-Host 'aguardando a UI subir...'
        $ok = $false
        foreach ($i in 1..90) {
            try {
                Invoke-RestMethod -Uri 'http://127.0.0.1:8000/api/saude' -TimeoutSec 3 | Out-Null
                $ok = $true; break
            } catch { Start-Sleep -Seconds 2 }
        }
        if (-not $ok) { Write-Error 'a UI nao respondeu'; exit 1 }
        Write-Host ''
        docker compose exec -T ui python -m anonimizador.web.modo
        Write-Host '  interface em http://127.0.0.1:8000'
        Write-Host ''
    }
    'ui-down'       { docker compose down --remove-orphans }
    'ui-llm'        {
        docker compose up -d ui ui-proxy analise
        Write-Host ''
        Write-Host '  interface : http://127.0.0.1:8000'
        docker compose exec -T analise python -c "import os;print('  chave     :', 'configurada' if os.getenv('OPENROUTER_API_KEY') else 'AUSENTE -- copie .env.example para .env')"
    }
    'llm-proof'     {
        docker compose up -d ui analise
        Write-Host ''
        Write-Host '--- 1: o servico ui NAO tem egress ---'
        docker compose exec -T ui python -m anonimizador.web.prova_rede
        Write-Host ''
        Write-Host '--- 2: o servico analise NAO enxerga a pasta das sessoes ---'
        docker compose exec -T analise python -c "import pathlib,sys; p=pathlib.Path('/app/out'); sys.exit(1) if p.exists() and any(p.iterdir()) else print('  /app/out inacessivel ou vazio: ok')"
        Write-Host ''
        Write-Host '--- 3: o servico analise TEM egress (e o unico que precisa) ---'
        docker compose exec -T analise python -c "import socket; socket.create_connection(('1.1.1.1',443),timeout=5).close(); print('  egress presente: ok')"
    }
    'ui-proof'      {
        docker compose up -d ui ui-proxy
        Write-Host 'aguardando a UI subir...'
        $ok = $false
        foreach ($i in 1..60) {
            try {
                Invoke-RestMethod -Uri 'http://127.0.0.1:8000/api/saude' -TimeoutSec 3 | Out-Null
                $ok = $true; break
            } catch { Start-Sleep -Seconds 2 }
        }
        if (-not $ok) { Write-Error 'a UI nao respondeu'; exit 1 }
        Write-Host ''
        Write-Host '--- metade 1: a porta responde do host ---'
        Invoke-RestMethod -Uri 'http://127.0.0.1:8000/api/saude' | ConvertTo-Json -Compress
        Write-Host ''
        Write-Host '--- metade 2: o servico ui nao tem egress ---'
        docker compose exec -T ui python -m anonimizador.web.prova_rede
    }
    'offline-proof' { docker compose run --rm offline-proof }
    'demo'          {
        docker compose run --rm cli redact `
            --in /app/eval/datasets/contrato-000.pdf `
            --out /app/out/contrato-000.redigido.pdf
    }
    'shell'         { docker compose run --rm dev }
    'tunel'         {
        # Expoe a UI para a internet por um tunel temporario do Cloudflare,
        # para demonstrar o sistema a alguem fora da sua rede.
        #
        # Nenhuma porta e aberta no roteador e nenhuma conta e necessaria: o
        # `cloudflared` abre uma conexao DE DENTRO para fora e devolve uma URL
        # `trycloudflare.com` aleatoria, que morre quando voce fecha.
        #
        # A TRAVA ABAIXO NAO E CERIMONIA. Sem login, publicar esta URL poria o
        # sistema inteiro aberto: qualquer um sobe documento, e quem tiver um
        # `doc_id` abre o documento de outra pessoa. O alvo recusa rodar nesse
        # estado, de proposito — e a recusa e o unico jeito de a pressa nao
        # virar vazamento.
        $saude = $null
        try { $saude = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/api/saude' -TimeoutSec 3 } catch {}
        if (-not $saude) {
            Write-Host ''
            Write-Host '  a UI nao esta no ar. Suba com:   ui'
            Write-Host ''
            exit 1
        }

        # A decisao mora em `web/modo.py`, nao aqui: um `grep` por frase
        # escrito duas vezes (Makefile e este arquivo) e duas chances de a
        # trava abrir por engano. `--exigir-login` sai 0 com login, 1 sem, e
        # imprime o motivo. `tests/test_modo.py` cobre os dois lados.
        docker compose exec -T ui python -m anonimizador.web.modo --exigir-login
        if ($LASTEXITCODE -ne 0) { exit 1 }

        if (-not (Get-Command cloudflared -ErrorAction SilentlyContinue)) {
            Write-Host ''
            Write-Host '  cloudflared nao encontrado. Instale com:'
            Write-Host '    winget install --id Cloudflare.cloudflared'
            Write-Host ''
            exit 1
        }

        Write-Host ''
        Write-Host '  Tunel temporario. A URL aparece abaixo, em poucos segundos.'
        Write-Host '  Ela morre quando voce fechar este terminal (Ctrl+C).'
        Write-Host ''
        Write-Host '  Lembre-se: quem receber a URL precisa de uma conta para entrar.'
        Write-Host ''
        cloudflared tunnel --url http://127.0.0.1:8000
    }
    'usuario'       {
        if (-not $Email -or -not $Inquilino) {
            Write-Host ''
            Write-Host '  uso:'
            Write-Host '    .\run.ps1 usuario -Email voce@exemplo.org -Inquilino "Seu Orgao"'
            Write-Host '    .\run.ps1 usuario EMAIL=voce@exemplo.org INQUILINO="Seu Orgao"'
            Write-Host ''
            Write-Host '  -Papel aceita operador, dono (padrao) ou plataforma.'
            Write-Host ''
            exit 1
        }
        # Pelo `cli-db`, que e o servico na rede `interna`: o `cli` roda em
        # `network_mode: none` e nao alcanca o Postgres.
        docker compose run --rm --entrypoint python cli-db -m anonimizador.cli `
            criar-usuario --email $Email --inquilino $Inquilino --papel $Papel
    }
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
        Write-Host '  diagnostico    por que PERSON vaza: nao detectado ou rotulo errado'
        Write-Host '  gate-usabilidade         monta a sessao de revisao com pessoas'
        Write-Host '  gate-usabilidade-apurar  le o registro.csv preenchido'
        Write-Host '  ui             sobe a interface em http://127.0.0.1:8000'
        Write-Host '  ui-recarregar  recarrega a UI depois de qualquer alteracao'
        Write-Host '  ui-down        derruba a interface'
        Write-Host '  ui-proof       prova que a UI responde E nao tem egress'
        Write-Host '  ui-llm         sobe a UI + o servico de analise por LLM externa'
        Write-Host '  llm-proof      prova que o ui segue sem egress e o analise nao ve o original'
        Write-Host '  offline-proof  prova que o pipeline roda sem rede'
        Write-Host '  demo           redige um documento do corpus'
        Write-Host '  shell          shell interativo no container'
        Write-Host '  usuario        cria usuario para o modo com login'
        Write-Host '  tunel          expoe a UI por um tunel temporario, para demonstrar'
        Write-Host '                   .\run.ps1 usuario -Email voce@ex.org -Inquilino "Seu Orgao"'
        Write-Host '  gpu-build      constroi a imagem com torch CUDA'
        Write-Host '  gpu-eval       avaliacao usando GPU'
        Write-Host '  clean          remove saidas geradas'
        Write-Host ''
    }
}
