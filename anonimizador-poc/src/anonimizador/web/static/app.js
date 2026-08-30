"use strict";

/* Interface de revisão.
 *
 * Regra que este arquivo respeita e que não é óbvia lendo o código:
 * **nada aqui produz o PDF.** Os retângulos desenhados são uma projeção do
 * que o servidor diz que vai tarjar. O arquivo nasce em /aprovar, no
 * servidor, e só é liberado se a verificação passar. Se esta tela e o PDF
 * discordarem, o PDF está certo — por isso o estado sempre vem de volta do
 * servidor a cada edição, em vez de ser atualizado localmente.
 */

const ESCALA = 2.0; // deve casar com o padrão de /pagina/{n}.png

let doc = null;

const $ = (id) => document.getElementById(id);

// ---------------------------------------------------------------- upload
$("arquivo").addEventListener("change", async (ev) => {
  const arquivo = ev.target.files[0];
  if (!arquivo) return;

  $("erro-upload").classList.add("hidden");
  $("carregando-upload").classList.remove("hidden");
  ev.target.disabled = true;

  const corpo = new FormData();
  corpo.append("arquivo", arquivo);
  try {
    const r = await fetch("/api/doc", { method: "POST", body: corpo });
    const dados = await r.json();
    if (!r.ok) throw new Error(dados.detail || "falha no envio");
    doc = dados;
    montarRevisao();
  } catch (e) {
    $("erro-upload").textContent = e.message;
    $("erro-upload").classList.remove("hidden");
  } finally {
    $("carregando-upload").classList.add("hidden");
    ev.target.disabled = false;
    ev.target.value = "";
  }
});

// --------------------------------------------------------------- montagem
function montarRevisao() {
  $("tela-upload").classList.add("hidden");
  $("tela-revisao").classList.remove("hidden");
  $("cabecalho-doc").classList.remove("hidden");
  $("nome-arquivo").textContent = doc.nome_arquivo;

  montarPaginas($("rolagem-esq"), false);
  montarPaginas($("rolagem-dir"), true);
  sincronizarRolagem();
  redesenhar();
}

function montarPaginas(container, comTarjas) {
  container.innerHTML = "";
  for (const p of doc.paginas) {
    const div = document.createElement("div");
    div.className = "pagina";
    div.dataset.n = p.numero;

    const img = document.createElement("img");
    img.src = `/api/doc/${doc.doc_id}/pagina/${p.numero}.png?escala=${ESCALA}`;
    img.alt = `página ${p.numero + 1}`;
    img.loading = "lazy";
    div.appendChild(img);

    if (comTarjas) {
      const camada = document.createElement("div");
      camada.className = "camada-tarjas";
      div.appendChild(camada);
      // As caixas são posicionadas em % da página, então não dependem de a
      // imagem já ter carregado nem de reposicionar no resize.
    }

    const rotulo = document.createElement("div");
    rotulo.className = "rotulo-pagina";
    rotulo.textContent = `${p.numero + 1} / ${doc.paginas.length}`;

    const embrulho = document.createElement("div");
    embrulho.appendChild(div);
    embrulho.appendChild(rotulo);
    container.appendChild(embrulho);
  }
}

/* Desenha as tarjas a partir do estado do servidor.
 * Coordenadas chegam em pontos de PDF; a página tem largura/altura em pontos.
 * Converter para porcentagem torna o posicionamento independente do zoom, do
 * tamanho da janela e de a imagem ter carregado ou não. */
function redesenhar() {
  const camadas = $("rolagem-dir").querySelectorAll(".camada-tarjas");
  camadas.forEach((c) => (c.innerHTML = ""));

  for (const s of doc.spans) {
    for (const r of s.rects) {
      const pagina = doc.paginas[r.pagina];
      const camada = camadas[r.pagina];
      if (!pagina || !camada) continue;

      const caixa = document.createElement("span");
      caixa.className = "tarja";
      if (!s.sera_tarjado) caixa.classList.add("desligada");
      if (s.origem === "usuario") caixa.classList.add("manual");
      caixa.style.left = (100 * r.x0) / pagina.largura + "%";
      caixa.style.top = (100 * r.y0) / pagina.altura + "%";
      caixa.style.width = (100 * (r.x1 - r.x0)) / pagina.largura + "%";
      caixa.style.height = (100 * (r.y1 - r.y0)) / pagina.altura + "%";
      caixa.title = `${s.entity} · ${s.sera_tarjado ? "será tarjado" : "NÃO será tarjado"}`;
      caixa.dataset.spanId = s.id;
      caixa.addEventListener("click", () => alternar(s.id, !s.ativo));
      camada.appendChild(caixa);
    }
  }
  montarInventario();
  atualizarBotaoAprovar();
}

function montarInventario() {
  const ul = $("inventario");
  ul.innerHTML = "";

  const porEntidade = {};
  for (const s of doc.spans) {
    const e = (porEntidade[s.entity] ||= { total: 0, tarjados: 0 });
    e.total += 1;
    if (s.sera_tarjado) e.tarjados += 1;
  }

  for (const [entidade, c] of Object.entries(porEntidade)) {
    const li = document.createElement("li");

    const chk = document.createElement("input");
    chk.type = "checkbox";
    chk.checked = c.tarjados > 0;
    chk.disabled = entidade === "MANUAL";
    chk.title =
      entidade === "MANUAL"
        ? "trechos que você apontou; sempre tarjados"
        : "ligar/desligar a classe inteira";
    chk.addEventListener("change", () => alternarEntidade(entidade, chk.checked));

    const nome = document.createElement("span");
    nome.className = "nome";
    nome.textContent = entidade;

    const qtd = document.createElement("span");
    qtd.className = "qtd";
    qtd.textContent = `${c.tarjados}/${c.total}`;

    li.append(chk, nome, qtd);
    ul.appendChild(li);
  }
}

function atualizarBotaoAprovar() {
  const algum = doc.spans.some((s) => s.sera_tarjado);
  $("btn-aprovar").disabled = !algum;
}

// ----------------------------------------------------------------- edição
async function enviar(caminho, opcoes) {
  const r = await fetch(`/api/doc/${doc.doc_id}${caminho}`, opcoes);
  const dados = await r.json();
  if (!r.ok) throw new Error(dados.detail || "falha");
  return dados;
}

async function alternar(spanId, ativo) {
  doc = await enviar("/span", {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ span_id: spanId, ativo }),
  });
  limparResultado();
  redesenhar();
}

async function alternarEntidade(entidade, ligar) {
  const regras = { ...doc.perfil.regras, [entidade]: ligar ? "tarja" : "manter" };
  doc = await enviar("/perfil", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      nome: "personalizado",
      padrao: doc.perfil.padrao,
      regras,
    }),
  });
  limparResultado();
  redesenhar();
}

$("btn-termo").addEventListener("click", adicionarTermo);
$("termo").addEventListener("keydown", (e) => {
  if (e.key === "Enter") adicionarTermo();
});

async function adicionarTermo() {
  const termo = $("termo").value.trim();
  const aviso = $("aviso-termo");
  if (termo.length < 2) return;

  $("btn-termo").disabled = true;
  try {
    doc = await enviar("/termo", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ termo }),
    });
    aviso.textContent =
      doc.adicionados > 0
        ? `${doc.adicionados} ocorrência(s) tarjada(s).`
        : "Nenhuma ocorrência nova encontrada — verifique a grafia exata.";
    aviso.classList.remove("hidden");
    $("termo").value = "";
    limparResultado();
    redesenhar();
  } catch (e) {
    aviso.textContent = e.message;
    aviso.classList.remove("hidden");
  } finally {
    $("btn-termo").disabled = false;
  }
}

// -------------------------------------------------------------- aprovação
function limparResultado() {
  $("resultado").classList.add("hidden");
  $("resultado").className = "hidden";
}

$("btn-aprovar").addEventListener("click", async () => {
  $("processando").classList.remove("hidden");
  $("btn-aprovar").disabled = true;
  limparResultado();
  try {
    doc = await enviar("/aprovar", { method: "POST" });
    mostrarResultado();
  } catch (e) {
    const r = $("resultado");
    r.className = "falha";
    r.innerHTML = `<div class="cabeca">Falhou</div><div>${escapar(e.message)}</div>`;
  } finally {
    $("processando").classList.add("hidden");
    atualizarBotaoAprovar();
    redesenhar();
  }
});

function mostrarResultado() {
  const rel = doc.relatorio;
  const r = $("resultado");
  r.className = rel.verificacao_ok ? "ok" : "falha";

  if (rel.verificacao_ok) {
    r.innerHTML = `
      <div class="cabeca">Verificação aprovada</div>
      <ul>
        <li>${rel.spans_redigidos} trechos redigidos, ${rel.retangulos} retângulos</li>
        <li>${rel.valores_checados} valores conferidos em ${rel.vetores.length} vetores</li>
        <li>nenhum valor sobreviveu no arquivo final</li>
      </ul>
      <a class="baixar" href="/api/doc/${doc.doc_id}/download">Baixar PDF anonimizado</a>`;
  } else {
    // Sem link de download. O gate não é cosmético: o arquivo foi apagado no
    // servidor, não existe caminho para baixá-lo.
    r.innerHTML = `
      <div class="cabeca">Verificação REPROVOU — arquivo não liberado</div>
      <ul>
        <li>${rel.total_vazamentos} ocorrência(s) sobreviveram</li>
        <li>vetores afetados: ${escapar(rel.vazamentos.join(", "))}</li>
      </ul>
      <p class="aviso">
        O PDF redigido foi descartado no servidor. Ajuste as tarjas e aprove de
        novo.
      </p>`;
  }
  r.classList.remove("hidden");
}

// ------------------------------------------------------------------ resto
$("btn-descartar").addEventListener("click", async () => {
  if (!confirm("Apagar o documento e todos os arquivos desta sessão?")) return;
  await fetch(`/api/doc/${doc.doc_id}`, { method: "DELETE" });
  location.reload();
});

/* Rolagem espelhada. A trava evita o laço infinito de cada painel reagir ao
 * scroll que ele mesmo causou no outro. */
function sincronizarRolagem() {
  const esq = $("rolagem-esq");
  const dir = $("rolagem-dir");
  let travado = false;

  const espelhar = (origem, destino) => () => {
    if (travado) return;
    travado = true;
    destino.scrollTop = origem.scrollTop;
    destino.scrollLeft = origem.scrollLeft;
    requestAnimationFrame(() => (travado = false));
  };

  esq.addEventListener("scroll", espelhar(esq, dir));
  dir.addEventListener("scroll", espelhar(dir, esq));
}

function escapar(s) {
  const d = document.createElement("div");
  d.textContent = String(s);
  return d.innerHTML;
}
