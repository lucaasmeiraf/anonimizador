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
$("arquivo").addEventListener("change", (ev) => {
  if (ev.target.files[0]) enviarArquivo(ev.target.files[0]);
});

/* Arrastar e soltar.
 *
 * `dragover` precisa de preventDefault ou o navegador abre o PDF numa aba e
 * o usuário perde a tela. Os contadores de entrada/saída evitam o piscar
 * clássico: passar sobre um filho dispara `dragleave` no pai. */
(() => {
  const zona = $("zona");
  let profundidade = 0;

  const parar = (e) => {
    e.preventDefault();
    e.stopPropagation();
  };

  ["dragenter", "dragover", "dragleave", "drop"].forEach((evt) =>
    zona.addEventListener(evt, parar)
  );

  zona.addEventListener("dragenter", () => {
    profundidade += 1;
    zona.classList.add("arrastando");
  });

  zona.addEventListener("dragleave", () => {
    profundidade -= 1;
    if (profundidade <= 0) zona.classList.remove("arrastando");
  });

  zona.addEventListener("drop", (e) => {
    profundidade = 0;
    zona.classList.remove("arrastando");
    const arquivo = e.dataTransfer.files[0];
    if (arquivo) enviarArquivo(arquivo);
  });

  // Soltar fora da zona não pode navegar para o arquivo.
  ["dragover", "drop"].forEach((evt) =>
    window.addEventListener(evt, (e) => e.preventDefault())
  );
})();

async function enviarArquivo(arquivo) {
  const erro = $("erro-upload");
  erro.classList.add("hidden");

  // Recusa antes de subir: erra rápido e não gasta a viagem.
  if (!/\.pdf$/i.test(arquivo.name) && arquivo.type !== "application/pdf") {
    erro.textContent = "Só PDF nesta fase.";
    erro.classList.remove("hidden");
    return;
  }

  $("carregando-upload").classList.remove("hidden");
  $("zona").classList.add("hidden");
  $("progresso-sub").textContent = `${arquivo.name} · ${formatarTamanho(
    arquivo.size
  )}`;

  const corpo = new FormData();
  corpo.append("arquivo", arquivo);
  try {
    const r = await fetch("/api/doc", { method: "POST", body: corpo });
    const dados = await r.json();
    if (!r.ok) throw new Error(dados.detail || "falha no envio");
    doc = dados;
    montarRevisao();
  } catch (e) {
    erro.textContent = e.message;
    erro.classList.remove("hidden");
    $("zona").classList.remove("hidden");
  } finally {
    $("carregando-upload").classList.add("hidden");
    $("arquivo").value = "";
  }
}

function formatarTamanho(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

// Qual modelo está detectando — muda o que esperar da revisão.
fetch("/api/saude")
  .then((r) => (r.ok ? r.json() : null))
  .then((d) => {
    if (d) {
      $("modelo-ativo").textContent =
        `Detecção por ${d.ner}, ${d.entidades} tipos de dado.`;
    }
  })
  .catch(() => {});

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

  // Só "apagar". Havia também um "desligar", que duplicava o clique na tarja
  // sem acrescentar nada e ainda assim confundia: o retângulo continuava
  // visível, tracejado, e parecia não ter obedecido. Para um trecho que o
  // próprio usuário adicionou, a intenção é remover, não manter desligado.
  for (const [valor, spans] of porValor) {
    const li = document.createElement("li");

    const txt = document.createElement("span");
    txt.className = "txt";
    txt.textContent = spans.length > 1 ? `${valor} (${spans.length}×)` : valor;
    txt.title = valor;

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

    li.append(txt, del);
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

/* ------------------------------------------------ seleção no documento ---
 *
 * `getSelection().toString()` NÃO serve aqui, e esse foi o bug que fazia o
 * botão parecer morto: cada palavra é um <span> posicionado em absoluto, sem
 * nenhum nó de espaço entre eles. O navegador concatena o que encontra, e o
 * resultado sai grudado — "OFÍCIONº359/2026" — que não existe em lugar
 * nenhum do documento. A busca não achava nada e nada acontecia.
 *
 * A reconstrução correta é percorrer os spans que a seleção toca, na ordem
 * do DOM (que é a ordem de leitura da extração), e juntá-los com espaço. */
function palavrasSelecionadas() {
  const sel = window.getSelection();
  if (!sel || sel.isCollapsed || !sel.rangeCount) return null;

  const range = sel.getRangeAt(0);
  const camada =
    range.commonAncestorContainer.nodeType === 1
      ? range.commonAncestorContainer.closest(".camada-texto")
      : range.commonAncestorContainer.parentElement?.closest(".camada-texto");
  if (!camada) return null; // seleção fora do documento (lateral, cabeçalho)

  const dentro = [...camada.children].filter((s) => range.intersectsNode(s));
  if (!dentro.length) return null;

  const texto = dentro
    .map((s) => s.textContent)
    .join(" ")
    .replace(/\s+/g, " ")
    .trim();

  return texto.length >= 2 ? { texto, range } : null;
}

const balao = $("balao");

function posicionarBalao(range) {
  const r = range.getBoundingClientRect();
  if (!r.width && !r.height) return esconderBalao();
  balao.style.left = `${r.left + r.width / 2}px`;
  // 10px acima do topo da seleção; o transform no CSS ancora pelo rodapé.
  balao.style.top = `${r.top - 10}px`;
  balao.classList.remove("hidden");
}

function esconderBalao() {
  balao.classList.add("hidden");
  balao.dataset.termo = "";
}

/* `selectionchange` dispara a cada caractere arrastado. Reagir a todos deixa
 * o balão tremendo junto do cursor, então ele só se posiciona quando o
 * usuário solta — que é quando a seleção está de fato pronta. */
document.addEventListener("selectionchange", () => {
  if (!palavrasSelecionadas()) esconderBalao();
});

document.addEventListener("mouseup", () => {
  // Clicar no próprio balão não pode reavaliar a seleção antes do clique.
  setTimeout(() => {
    const sel = palavrasSelecionadas();
    if (!sel) return esconderBalao();
    balao.dataset.termo = sel.texto;
    $("balao-texto").textContent =
      sel.texto.length > 32 ? sel.texto.slice(0, 32) + "…" : sel.texto;
    posicionarBalao(sel.range);
  }, 0);
});

// O balão é `position: fixed`; ao rolar, a seleção sai de baixo dele.
window.addEventListener("scroll", esconderBalao, true);

$("balao-tarjar").addEventListener("mousedown", (e) => e.preventDefault());
$("balao-tarjar").addEventListener("click", async () => {
  const termo = balao.dataset.termo;
  esconderBalao();
  window.getSelection()?.removeAllRanges();
  if (termo) await adicionarTermo(termo);
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

/* A sincronia entre os painéis deixou de ser código.
 *
 * Antes cada painel tinha rolagem própria e o JavaScript espelhava
 * `scrollTop` de um no outro, com uma trava para não entrar em laço. Agora a
 * rolagem é da página: os dois painéis são colunas do mesmo grid, com a mesma
 * altura, e sobem juntos por construção. Nada para espelhar, nada para
 * destravar, nada que possa sair de sincronia. */
function sincronizarRolagem() {}

function escapar(s) {
  const d = document.createElement("div");
  d.textContent = String(s);
  return d.innerHTML;
}
