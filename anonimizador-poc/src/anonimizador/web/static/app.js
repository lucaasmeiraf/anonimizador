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

    // Camada de texto selecionável, nos dois painéis. É o que permite o
    // Ctrl+C do usuário — a página é uma imagem e imagem não tem texto.
    const texto = document.createElement("div");
    texto.className = "camada-texto";
    div.appendChild(texto);
    carregarTexto(p, texto);

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

/* Desenha as palavras como texto transparente sobre a imagem.
 *
 * Posição e largura vêm em pontos de PDF e viram porcentagem, como as tarjas.
 * A altura da caixa define o tamanho da fonte; a largura raramente bate com a
 * da fonte do sistema, então um scaleX corrige — sem isso a seleção fica
 * visivelmente deslocada do que a imagem mostra. */
async function carregarTexto(pagina, camada) {
  let dados;
  try {
    const r = await fetch(`/api/doc/${doc.doc_id}/texto/${pagina.numero}`);
    if (!r.ok) return;
    dados = await r.json();
  } catch {
    return; // sem camada de texto a tela continua utilizável
  }

  const frag = document.createDocumentFragment();
  for (const p of dados.palavras) {
    const s = document.createElement("span");
    s.textContent = p.t;
    const alturaPt = p.y1 - p.y0;
    s.style.left = (100 * p.x0) / pagina.largura + "%";
    s.style.top = (100 * p.y0) / pagina.altura + "%";
    s.style.fontSize = (100 * alturaPt) / pagina.altura + "%";
    s.dataset.larguraPt = p.x1 - p.x0;
    frag.appendChild(s);
  }
  camada.appendChild(frag);

  // O ajuste de largura precisa do texto já no DOM para medir.
  requestAnimationFrame(() => {
    const larguraPx = camada.clientWidth;
    if (!larguraPx) return;
    for (const s of camada.children) {
      const alvoPx = (s.dataset.larguraPt / pagina.largura) * larguraPx;
      const real = s.getBoundingClientRect().width;
      if (real > 0 && alvoPx > 0) {
        s.style.transform = `scaleX(${alvoPx / real})`;
      }
    }
  });
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
  montarListaManuais();
  atualizarBotaoAprovar();
}

/* Lista dos trechos que o usuário adicionou, com desligar e apagar.
 *
 * Desligar não bastava: um termo digitado errado espalha retângulos pelo
 * documento e obriga a caçar cada um na página para clicar. Aqui eles estão
 * todos juntos, e apagar remove de vez. */
function montarListaManuais() {
  const caixa = $("manuais");
  const ul = $("lista-manuais");
  const manuais = doc.spans.filter((s) => s.origem === "usuario");

  ul.innerHTML = "";
  caixa.classList.toggle("hidden", manuais.length === 0);
  if (!manuais.length) return;

  // Um termo vira vários spans (uma por ocorrência); agrupa por texto.
  const porValor = new Map();
  for (const s of manuais) {
    if (!porValor.has(s.valor)) porValor.set(s.valor, []);
    porValor.get(s.valor).push(s);
  }

  for (const [valor, spans] of porValor) {
    const ligados = spans.filter((s) => s.ativo).length;
    const li = document.createElement("li");

    const txt = document.createElement("span");
    txt.className = "txt" + (ligados ? "" : " off");
    txt.textContent = spans.length > 1 ? `${valor} (${spans.length}×)` : valor;
    txt.title = valor;

    const alt = document.createElement("button");
    alt.textContent = ligados ? "desligar" : "ligar";
    alt.addEventListener("click", async () => {
      for (const s of spans) await alternar(s.id, !ligados, false);
      redesenhar();
    });

    const del = document.createElement("button");
    del.textContent = "apagar";
    del.title = "remove estes trechos da proposta";
    del.addEventListener("click", async () => {
      for (const s of spans) {
        doc = await enviar(`/span/${s.id}`, { method: "DELETE" });
      }
      limparResultado();
      redesenhar();
    });

    li.append(txt, alt, del);
    ul.appendChild(li);
  }
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

async function alternar(spanId, ativo, redesenhaDepois = true) {
  doc = await enviar("/span", {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ span_id: spanId, ativo }),
  });
  limparResultado();
  if (redesenhaDepois) redesenhar();
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

$("btn-termo").addEventListener("click", () => adicionarTermo());
$("termo").addEventListener("keydown", (e) => {
  if (e.key === "Enter") adicionarTermo();
});

/* Seleção no documento vira termo com um clique.
 *
 * O Ctrl+C do navegador continua funcionando — a camada de texto é texto de
 * verdade. Este botão só evita a viagem até o campo para colar. */
$("btn-selecao").addEventListener("click", () => {
  const sel = selecaoAtual();
  if (sel) adicionarTermo(sel);
});

function selecaoAtual() {
  const s = window.getSelection();
  if (!s || s.isCollapsed) return "";
  // Só interessa seleção feita dentro do documento, não na lateral.
  const dentro =
    s.anchorNode &&
    s.anchorNode.parentElement &&
    s.anchorNode.parentElement.closest(".camada-texto");
  const txt = s.toString().replace(/\s+/g, " ").trim();
  return dentro && txt.length >= 2 ? txt : "";
}

document.addEventListener("selectionchange", () => {
  const sel = selecaoAtual();
  const btn = $("btn-selecao");
  btn.classList.toggle("hidden", !sel);
  if (sel) {
    const curto = sel.length > 40 ? sel.slice(0, 40) + "…" : sel;
    btn.textContent = `Tarjar "${curto}"`;
  }
});

async function adicionarTermo(valor) {
  const termo = (valor !== undefined ? valor : $("termo").value).trim();
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
    //
    // Mas "reprovou" sozinho é um beco sem saída. Cada ocorrência vira um
    // cartão que diz *o que* sobreviveu, *onde*, e — quando o conserto está
    // ao alcance do usuário — oferece o botão que o faz.
    const ocorrencias = rel.ocorrencias || [];
    const acionaveis = ocorrencias.filter((o) => o.visivel_no_texto);

    let corpo = `
      <div class="cabeca">Verificação reprovou — arquivo não liberado</div>
      <ul>
        <li>${rel.total_vazamentos} ocorrência(s) sobreviveram ao saneamento</li>
        <li>vetores afetados: ${escapar(rel.vazamentos.join(", "))}</li>
      </ul>`;

    if (acionaveis.length) {
      corpo += `<p class="aviso">
        Estes trechos ainda aparecem no texto do documento — quase sempre é
        outra ocorrência do mesmo valor que o detector não marcou.
      </p>`;
    }

    r.innerHTML = corpo;

    for (const o of ocorrencias) {
      const card = document.createElement("div");
      card.className = "ocorrencia" + (o.visivel_no_texto ? "" : " estrutural");

      const quem = document.createElement("div");
      quem.className = "quem";
      quem.textContent = o.valor;

      const onde = document.createElement("div");
      onde.className = "onde";
      onde.textContent = o.visivel_no_texto
        ? `${o.ocorrencias_no_texto} ocorrência(s) legíveis no texto`
        : `só na estrutura do PDF${o.objeto ? " — " + o.objeto : ""} ` +
          `(${o.vetores.join(", ")})`;

      card.append(quem, onde);

      if (o.visivel_no_texto) {
        const b = document.createElement("button");
        b.textContent = "Tarjar todas as ocorrências";
        b.addEventListener("click", () => adicionarTermo(o.valor));
        card.appendChild(b);
      }
      r.appendChild(card);
    }

    if (ocorrencias.length && !acionaveis.length) {
      const p = document.createElement("p");
      p.className = "aviso";
      p.textContent =
        "Nenhuma destas sai por extração de texto — o valor sobrevive num " +
        "objeto interno do PDF. Isso é defeito do redator, não da sua " +
        "revisão; reporte o tipo de objeto acima.";
      r.appendChild(p);
    }
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
