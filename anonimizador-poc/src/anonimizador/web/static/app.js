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
    lembrarSessao(doc.doc_id);
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

/* ------------------------------------------------ sessão entre recargas ---
 *
 * A revisão vive no servidor; o navegador só guarda qual é. Sem isto, um F5
 * acidental jogava fora todo o trabalho de revisão — as tarjas desligadas, os
 * trechos apontados à mão — enquanto a sessão continuava lá, intacta e
 * inalcançável.
 *
 * Só o identificador é guardado. Nenhum conteúdo de documento passa pelo
 * armazenamento do navegador.
 */
const CHAVE_SESSAO = "anonimizador.doc";

function lembrarSessao(id) {
  try {
    localStorage.setItem(CHAVE_SESSAO, id);
  } catch {
    /* modo privado, cota cheia: perder a retomada não pode quebrar a tela */
  }
}

function esquecerSessao() {
  try {
    localStorage.removeItem(CHAVE_SESSAO);
  } catch {}
}

async function restaurarSessao() {
  let id = null;
  try {
    id = localStorage.getItem(CHAVE_SESSAO);
  } catch {
    return;
  }
  if (!id) return;

  try {
    const r = await fetch(`/api/doc/${id}`);
    // 404 é o caso normal: a sessão expirou, foi descartada, ou o servidor
    // reiniciou. Não é erro — é só não haver o que retomar.
    if (!r.ok) return esquecerSessao();
    doc = await r.json();
    montarRevisao();
  } catch {
    esquecerSessao();
  }
}

restaurarSessao();

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
      // Camada de texto selecionável **só no painel Anonimizado**.
      //
      // Antes existia nos dois, e isso confundia: o usuário selecionava à
      // esquerda para agir sobre o que aparece à direita. Aqui a seleção e o
      // efeito ficam no mesmo lugar — você seleciona o que *ainda* está
      // legível e manda tarjar.
      //
      // Consequência aceita: o painel Original deixa de ter Ctrl+C, e texto
      // sob uma tarja não é selecionável, porque o retângulo intercepta o
      // mouse. Este segundo caso é o comportamento correto: aquele trecho já
      // está tarjado.
      const texto = document.createElement("div");
      texto.className = "camada-texto";
      div.appendChild(texto);
      carregarTexto(p, texto);

      // As caixas são posicionadas em % da página, então não dependem de a
      // imagem já ter carregado nem de reposicionar no resize.
      const camada = document.createElement("div");
      camada.className = "camada-tarjas";
      div.appendChild(camada);
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
 * A posição vai em porcentagem — ela é relativa à caixa da página, e
 * porcentagem resolve isso sozinha em qualquer zoom.
 *
 * O **tamanho da fonte não pode** ir em porcentagem, e essa foi a origem de
 * dois defeitos que pareciam não ter relação:
 *
 *   font-size: 1.19%   →  1.19% de 14px (a fonte herdada)  =  0.17px
 *
 * `font-size` em `%` é percentual da fonte do **elemento pai**, não da altura
 * do container. A camada inteira ficava microscópica, e daí:
 *
 *   * o realce da seleção tinha 0.17px de altura — invisível, e o usuário
 *     selecionava sem nenhum retorno visual;
 *   * a largura medida era quase zero, então o `scaleX` de correção calculava
 *     um fator gigante e esticava cada palavra por cima da linha inteira.
 *     Arrastar o cursor atravessava dezenas de spans sobrepostos, e a seleção
 *     pegava muito mais do que o apontado.
 *
 * O tamanho tem de ser calculado em pixels, a partir da altura **renderizada**
 * da página — que só se conhece depois de a imagem carregar, e muda quando a
 * janela muda. Daí o `ResizeObserver`. */
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
    s.style.left = (100 * p.x0) / pagina.largura + "%";
    s.style.top = (100 * p.y0) / pagina.altura + "%";
    // Métricas em pontos de PDF; a conversão para pixel acontece no ajuste,
    // porque depende do tamanho com que a página foi de fato desenhada.
    s.dataset.alturaPt = p.y1 - p.y0;
    s.dataset.larguraPt = p.x1 - p.x0;
    // Offset desta palavra no texto completo do documento. É a ponte entre o
    // que o navegador selecionou e o que o servidor vai tarjar: somado ao
    // deslocamento dentro do nó de texto, dá o caractere exato.
    s.dataset.i = p.i;
    frag.appendChild(s);
  }
  camada.appendChild(frag);

  const ajustar = () => ajustarCamadaDeTexto(camada, pagina);
  ajustar();

  // A altura útil só existe depois que a imagem da página carrega, e muda
  // junto com a janela. Sem reajustar, a camada fica fora de escala e a
  // seleção volta a não corresponder ao que se vê.
  const alvo = camada.parentElement;
  if (window.ResizeObserver && alvo) {
    new ResizeObserver(ajustar).observe(alvo);
  } else {
    window.addEventListener("resize", ajustar);
  }
}

/* Converte as métricas de ponto para pixel, com a página já renderizada. */
function ajustarCamadaDeTexto(camada, pagina) {
  const larguraPx = camada.clientWidth;
  const alturaPx = camada.clientHeight;
  if (!larguraPx || !alturaPx) return;

  const pxPorPontoV = alturaPx / pagina.altura;
  const pxPorPontoH = larguraPx / pagina.largura;

  for (const s of camada.children) {
    // Primeiro o tamanho, em pixel de verdade.
    s.style.transform = "none";
    s.style.fontSize = Number(s.dataset.alturaPt) * pxPorPontoV + "px";
  }

  // A medição de largura precisa acontecer depois de todos os tamanhos já
  // aplicados — lê-la no mesmo laço forçaria um reflow por palavra.
  for (const s of camada.children) {
    const alvoPx = Number(s.dataset.larguraPt) * pxPorPontoH;
    const real = s.getBoundingClientRect().width;
    // A fonte do sistema quase nunca tem a mesma largura da fonte embutida no
    // PDF; o scaleX faz a caixa do texto coincidir com o que a imagem mostra,
    // que é o que faz o realce da seleção cair sobre as letras certas.
    if (real > 0.5 && alvoPx > 0) {
      s.style.transform = `scaleX(${alvoPx / real})`;
    }
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
      // Detectado pela forma, não pelo dígito verificador. É palpite forte,
      // não certeza matemática, e o revisor precisa saber a diferença.
      if (s.nota === "checksum_invalido") caixa.classList.add("suspeita");
      caixa.style.left = (100 * r.x0) / pagina.largura + "%";
      caixa.style.top = (100 * r.y0) / pagina.altura + "%";
      caixa.style.width = (100 * (r.x1 - r.x0)) / pagina.largura + "%";
      caixa.style.height = (100 * (r.y1 - r.y0)) / pagina.altura + "%";
      const porque =
        s.nota === "checksum_invalido"
          ? " · forma válida, dígito verificador inválido — confira"
          : "";
      caixa.title =
        `${s.entity} · ${s.sera_tarjado ? "será tarjado" : "NÃO será tarjado"}` +
        porque;
      caixa.dataset.spanId = s.id;
      /* Clique na tarja: o que ele significa depende de quem a criou.
       *
       * Proposta do detector -> **desliga**, e o retângulo continua ali,
       * tracejado. O revisor precisa enxergar o que o sistema achou e ele
       * recusou; fazer sumir esconderia justamente a informação que torna a
       * revisão auditável.
       *
       * Trecho que o usuário adicionou -> **remove**. Ele não propôs nada,
       * ele mandou tarjar; clicar é desfazer. Desligar deixava um retângulo
       * tracejado no lugar, e a leitura correta disso é "não saiu". */
      caixa.addEventListener("click", () =>
        s.origem === "usuario" ? removerSpan(s.id) : alternar(s.id, !s.ativo)
      );
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

/* Inventário.
 *
 * Mostra **todas** as entidades que a política cobre, inclusive as que não
 * apareceram. Listar só o que foi detectado fazia "procurei e não há" parecer
 * igual a "não sei procurar" — as duas somem da tela do mesmo jeito, e a
 * leitura natural é a segunda. Com a linha zerada visível, o usuário vê que a
 * ferramenta olhou. */
function montarInventario() {
  const ul = $("inventario");
  ul.innerHTML = "";

  const porEntidade = {};
  // O inventário do servidor já traz as zeradas; os spans dão os tarjados.
  for (const [entidade, total] of Object.entries(doc.inventario || {})) {
    porEntidade[entidade] = { total, tarjados: 0 };
  }
  for (const s of doc.spans) {
    const e = (porEntidade[s.entity] ||= { total: 0, tarjados: 0 });
    if (s.sera_tarjado) e.tarjados += 1;
  }

  for (const [entidade, c] of Object.entries(porEntidade)) {
    const vazia = c.total === 0;
    const li = document.createElement("li");
    if (vazia) li.className = "vazia";

    const chk = document.createElement("input");
    chk.type = "checkbox";
    chk.checked = c.tarjados > 0;
    // Sem ocorrência não há o que ligar; MANUAL é sempre tarjado por ser
    // intenção explícita do usuário.
    chk.disabled = vazia || entidade === "MANUAL";
    chk.title = vazia
      ? "nenhuma ocorrência encontrada neste documento"
      : entidade === "MANUAL"
        ? "trechos que você apontou; sempre tarjados"
        : "ligar/desligar a classe inteira";
    chk.addEventListener("change", () => alternarEntidade(entidade, chk.checked));

    const nome = document.createElement("span");
    nome.className = "nome";
    nome.textContent = entidade;

    const qtd = document.createElement("span");
    qtd.className = "qtd";
    qtd.textContent = vazia ? "—" : `${c.tarjados}/${c.total}`;

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

async function removerSpan(spanId) {
  doc = await enviar(`/span/${spanId}`, { method: "DELETE" });
  limparResultado();
  redesenhar();
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
/* Converte a seleção do navegador num intervalo de caracteres do documento.
 *
 * Cada <span> é uma palavra e carrega, em `data-i`, o offset dela no texto
 * completo. O navegador informa em que caractere *dentro* do nó de texto a
 * seleção começou e terminou. A soma dos dois dá o offset exato — inclusive
 * quando o usuário seleciona no meio de uma palavra.
 *
 * Devolve também o texto, usado só para exibir no balão. Quem manda no que
 * será tarjado são os offsets. */
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
  if (texto.length < 1) return null;

  // Offsets exatos das pontas.
  const primeiro = dentro[0];
  const ultimo = dentro[dentro.length - 1];
  const spanDe = (no) => (no.nodeType === 1 ? no : no.parentElement);

  let inicio = Number(primeiro.dataset.i);
  let fim = Number(ultimo.dataset.i) + ultimo.textContent.length;

  // A ponta só desloca quando ela cai *dentro* de uma palavra; se a seleção
  // começou no espaço entre palavras, o offset da palavra inteira já está
  // certo.
  const spanIni = spanDe(range.startContainer);
  if (spanIni === primeiro && range.startContainer.nodeType === 3) {
    inicio = Number(primeiro.dataset.i) + range.startOffset;
  }
  const spanFim = spanDe(range.endContainer);
  if (spanFim === ultimo && range.endContainer.nodeType === 3) {
    fim = Number(ultimo.dataset.i) + range.endOffset;
  }

  if (!Number.isFinite(inicio) || !Number.isFinite(fim) || fim <= inicio) {
    return null;
  }
  return { texto, range, inicio, fim };
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
    balao.dataset.inicio = sel.inicio;
    balao.dataset.fim = sel.fim;
    balao.dataset.texto = sel.texto;
    $("balao-texto").textContent =
      sel.texto.length > 32 ? sel.texto.slice(0, 32) + "…" : sel.texto;
    posicionarBalao(sel.range);
  }, 0);
});

// O balão é `position: fixed`; ao rolar, a seleção sai de baixo dele.
window.addEventListener("scroll", esconderBalao, true);

$("balao-tarjar").addEventListener("mousedown", (e) => e.preventDefault());
$("balao-tarjar").addEventListener("click", async () => {
  const inicio = Number(balao.dataset.inicio);
  const fim = Number(balao.dataset.fim);
  const textoSel = balao.dataset.texto || "";
  esconderBalao();
  window.getSelection()?.removeAllRanges();
  if (!Number.isFinite(inicio) || !Number.isFinite(fim)) return;

  const aviso = $("aviso-termo");
  try {
    // Intervalo, não termo: tarja só o que foi selecionado. Buscar o texto no
    // documento tarjaria todas as ocorrências, que não é o que selecionar
    // significa.
    doc = await enviar("/intervalo", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      // O texto vai junto para o servidor poder conferir que os offsets
      // apontam para o mesmo trecho que apareceu na tela.
      body: JSON.stringify({ inicio, fim, texto: textoSel }),
    });
    aviso.classList.add("hidden");
    limparResultado();
    redesenhar();
  } catch (e) {
    aviso.textContent = e.message;
    aviso.classList.remove("hidden");
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
      <a class="baixar" id="link-baixar" href="/api/doc/${doc.doc_id}/download">Baixar PDF anonimizado</a>`;
    // O download é uma navegação comum do navegador; o modal vem logo depois,
    // com folga para o arquivo ter começado a descer.
    r.querySelector("#link-baixar")?.addEventListener("click", () => {
      setTimeout(abrirProximo, 1200);
    });
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

// -------------------------------------------------------------- descarte
/* Modal próprio no lugar do `confirm()`.
 *
 * Não é só estética: o diálogo do navegador não permite explicar **o que**
 * está sendo destruído, e aqui a ação apaga o original, a proposta e o PDF
 * gerado, sem volta. Quem confirma precisa saber disso. */
/* Mecânica compartilhada pelos modais.
 *
 * Só a mecânica: cada modal tem a sua marcação e os seus botões. A parte que
 * vale a pena compartilhar é o comportamento de teclado, que é fácil de errar
 * e igual em todos — Esc fecha, Tab não escapa para a tela inerte atrás, e o
 * foco volta para onde estava.
 */
let modalAberto = null;
let focoAnterior = null;

function abrirModalEl(fundo, focoInicial) {
  focoAnterior = document.activeElement;
  modalAberto = fundo;
  fundo.classList.remove("hidden");
  focoInicial?.focus();
  document.addEventListener("keydown", teclaNoModal);
}

function fecharModalEl(fundo) {
  fundo.classList.add("hidden");
  if (modalAberto === fundo) modalAberto = null;
  document.removeEventListener("keydown", teclaNoModal);
  focoAnterior?.focus();
}

function teclaNoModal(e) {
  if (!modalAberto) return;
  if (e.key === "Escape") return fecharModalEl(modalAberto);
  if (e.key !== "Tab") return;
  // Prende o Tab dentro do modal: sair dele com o teclado deixaria o usuário
  // navegando numa tela que está inerte atrás da sobreposição.
  const foco = [...modalAberto.querySelectorAll("button")];
  const i = foco.indexOf(document.activeElement);
  if (i === -1) return;
  e.preventDefault();
  foco[(i + (e.shiftKey ? foco.length - 1 : 1)) % foco.length].focus();
}

// Clique na sobreposição cancela; clique dentro do cartão, não.
function fecharAoClicarFora(fundo) {
  fundo.addEventListener("click", (e) => {
    if (e.target === fundo) fecharModalEl(fundo);
  });
}

const modalFundo = $("modal-fundo");
// Foco no botão seguro: Enter sem ler não pode destruir a sessão.
const abrirModal = () => abrirModalEl(modalFundo, $("modal-cancelar"));
const fecharModal = () => fecharModalEl(modalFundo);

$("btn-descartar").addEventListener("click", abrirModal);
$("modal-cancelar").addEventListener("click", fecharModal);
fecharAoClicarFora(modalFundo);

$("modal-confirmar").addEventListener("click", async () => {
  const btn = $("modal-confirmar");
  btn.disabled = true;
  btn.textContent = "Descartando…";
  try {
    // Espera o servidor confirmar que apagou **antes** de limpar a tela. Com
    // `location.reload()` a tela voltava ao início sem garantia nenhuma de
    // que os arquivos tinham sumido.
    const r = await fetch(`/api/doc/${doc.doc_id}`, { method: "DELETE" });
    if (!r.ok && r.status !== 404) throw new Error("o servidor recusou apagar");
    fecharModal();
    voltarAoInicio();
  } catch (e) {
    // Erro dentro do próprio modal: um `alert()` aqui traria de volta a caixa
    // do navegador que este modal existe para substituir.
    const alerta = $("modal-corpo").querySelector(".alerta");
    alerta.textContent = `Não foi possível descartar: ${e.message}. Os arquivos continuam no servidor.`;
  } finally {
    btn.textContent = "Descartar";
    btn.disabled = false;
  }
});

/* ------------------------------------------------ depois do download -----
 *
 * Aparece só quando o PDF já foi liberado e baixado. Nesse ponto, descartar a
 * sessão não perde trabalho nenhum — o entregável está na máquina do
 * usuário —, e deixá-la viva mantém o documento original em disco sem motivo.
 *
 * "Continuar revisando" existe porque o download pode ter sido um teste: a
 * pessoa quer conferir o arquivo antes de abrir mão da sessão.
 */
const proximoFundo = $("proximo-fundo");
const abrirProximo = () => abrirModalEl(proximoFundo, $("proximo-novo"));
fecharAoClicarFora(proximoFundo);

$("proximo-fechar").addEventListener("click", () => fecharModalEl(proximoFundo));

async function encerrarSessao() {
  const id = doc?.doc_id;
  fecharModalEl(proximoFundo);
  if (id) {
    // Falhar aqui não pode travar a tela; o TTL da sessão recolhe depois.
    try {
      await fetch(`/api/doc/${id}`, { method: "DELETE" });
    } catch {}
  }
  voltarAoInicio();
}

$("proximo-inicio").addEventListener("click", encerrarSessao);

$("proximo-novo").addEventListener("click", async () => {
  await encerrarSessao();
  // Abre o seletor direto: o usuário já disse o que quer fazer.
  $("arquivo").click();
});

/* Volta à tela inicial sem recarregar a página: o modelo já está carregado no
 * servidor e o recarregamento só adicionaria um piscar. */
function voltarAoInicio() {
  esquecerSessao();
  doc = null;
  esconderBalao();
  window.getSelection()?.removeAllRanges();

  $("rolagem-esq").innerHTML = "";
  $("rolagem-dir").innerHTML = "";
  $("inventario").innerHTML = "";
  $("lista-manuais").innerHTML = "";
  $("manuais").classList.add("hidden");
  $("termo").value = "";
  $("aviso-termo").classList.add("hidden");
  limparResultado();

  $("tela-revisao").classList.add("hidden");
  $("cabecalho-doc").classList.add("hidden");
  $("tela-upload").classList.remove("hidden");
  $("zona").classList.remove("hidden");
  $("erro-upload").classList.add("hidden");
  $("arquivo").value = "";
  window.scrollTo(0, 0);
}

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
