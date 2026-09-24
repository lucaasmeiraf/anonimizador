"use strict";

/* Interface de revisão.
 *
 * Regra que este arquivo respeita e que não é óbvia lendo o código:
 * **nada aqui produz o PDF.** As marcações desenhadas são uma projeção do
 * que o servidor diz que vai sair do documento. O arquivo nasce em /aprovar,
 * no servidor, e só é liberado se a verificação passar. Se esta tela e o PDF
 * discordarem, o PDF está certo — por isso o estado sempre vem de volta do
 * servidor a cada edição, em vez de ser atualizado localmente.
 *
 * O que é só desta tela, e por isso pode morar aqui: qual modo de visualização
 * está aberto, o zoom, qual ocorrência está em foco e quais o revisor já
 * visitou. Nada disso chega ao servidor nem muda o arquivo.
 */

const ESCALA = 2.0; // deve casar com o padrão de /pagina/{n}.png
const ESCALA_MINIATURA = 0.5; // o mínimo que a rota aceita

let doc = null;

const $ = (id) => document.getElementById(id);

// Abaixo de 1024px o inspetor vira gaveta e "Comparar" sai; abaixo de 1280px
// o trilho de miniaturas nasce recolhido.
const telaEstreita = window.matchMedia("(max-width: 1023px)");
const telaMedia = window.matchMedia("(max-width: 1279px)");

/* ------------------------------------------------------------ categorias ---
 *
 * Nome em português, grupo e cor de cada entidade. A cor nunca é a única
 * pista: a dica, o popover e a lista sempre dizem o nome da categoria.
 * Entidade que não esteja aqui cai em "Identificação pessoal" com o nome
 * técnico — aparecer feio é melhor que sumir. */
const GRUPOS = [
  { id: "ident", rotulo: "Identificação pessoal" },
  { id: "contato", rotulo: "Contato e endereço" },
  { id: "contexto", rotulo: "Contexto" },
  { id: "manual", rotulo: "Adicionados por você" },
];

const CATEGORIAS = {
  PERSON: { nome: "Pessoas", singular: "Pessoa", grupo: "ident", cor: "pessoa" },
  CPF: { nome: "CPF", singular: "CPF", grupo: "ident", cor: "doc" },
  RG: { nome: "RG", singular: "RG", grupo: "ident", cor: "doc" },
  CNH: { nome: "CNH", singular: "CNH", grupo: "ident", cor: "doc" },
  CNS: { nome: "Cartão SUS (CNS)", singular: "Cartão SUS", grupo: "ident", cor: "doc" },
  PIS_PASEP: { nome: "PIS/PASEP", singular: "PIS/PASEP", grupo: "ident", cor: "doc" },
  TITULO_ELEITOR: { nome: "Título de eleitor", singular: "Título de eleitor", grupo: "ident", cor: "doc" },
  CNPJ: { nome: "CNPJ", singular: "CNPJ", grupo: "ident", cor: "doc" },
  PROCESSO_CNJ: { nome: "Processos judiciais", singular: "Processo judicial", grupo: "ident", cor: "doc" },
  EMAIL: { nome: "E-mail", singular: "E-mail", grupo: "contato", cor: "contato" },
  TELEFONE: { nome: "Telefone", singular: "Telefone", grupo: "contato", cor: "contato" },
  CEP: { nome: "CEP", singular: "CEP", grupo: "contato", cor: "local" },
  ENDERECO: { nome: "Endereços", singular: "Endereço", grupo: "contato", cor: "local" },
  LOCATION: { nome: "Locais", singular: "Local", grupo: "contato", cor: "local" },
  DATE_TIME: { nome: "Datas", singular: "Data", grupo: "contexto", cor: "data" },
  ORGANIZATION: { nome: "Órgãos e empresas", singular: "Órgão ou empresa", grupo: "contexto", cor: "org" },
  MANUAL: { nome: "Termos adicionados", singular: "Termo adicionado", grupo: "manual", cor: "manual" },
};

function categoria(entidade) {
  return (
    CATEGORIAS[entidade] || {
      nome: entidade,
      singular: entidade,
      grupo: "ident",
      cor: "neutro",
    }
  );
}

/* Os vetores da verificação, em português. Vetor desconhecido aparece com o
 * nome técnico: é melhor que esconder um vetor novo do checklist. */
const NOMES_VETORES = {
  texto: "Texto extraído",
  "texto-pymupdf": "Texto por palavra",
  "texto-pdfplumber": "Texto por outro extrator",
  anotacoes: "Anotações",
  acroform: "Campos de formulário",
  anexos: "Arquivos anexados",
  sumario: "Sumário e marcadores",
  metadados: "Metadados",
  xmp: "Metadados XMP",
  streams: "Conteúdo interno das páginas",
  "bytes-brutos": "Bytes do arquivo",
  "tokens-presentes": "Todo código foi escrito",
};

/* As etapas são dados, não marcação. A análise por IA entra como uma quarta
 * linha aqui — `{ id: "analisar", rotulo: "Analisar com IA" }` — com a regra
 * de status dela em `statusDaEtapa`, sem mexer no layout. */
const ETAPAS = [
  { id: "revisar", rotulo: "Revisar" },
  { id: "verificar", rotulo: "Verificar" },
  { id: "exportar", rotulo: "Exportar" },
];

/* Estado **só da tela**. Nada aqui muda o que o PDF vai ter. */
const estado = {
  vista: "anonimizado", // anonimizado | original | comparar
  previaFinal: false, // "Ver como ficará"
  zoom: 1,
  aba: "deteccoes",
  expandidas: new Set(),
  focado: null, // id do span em foco
  revisados: new Set(),
  cicloGrupo: new Map(),
  previa: null, // último resultado da pré-verificação, para `doc.versao`
  verificando: false,
  ocupado: false,
  sucesso: false,
  exportou: false, // algum arquivo desta revisão já foi baixado
};

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

/* Etapas do carregamento: só as que existem de fato. O envio tem progresso
 * medido; extração e detecção acontecem numa única chamada ao servidor, e
 * separá-las na tela seria inventar uma barra. */
function marcarEtapaUpload(atual) {
  const ordem = ["etapa-envio", "etapa-deteccao", "etapa-pronto"];
  const i = ordem.indexOf(atual);
  ordem.forEach((id, j) => {
    $(id).dataset.status = j < i ? "feito" : j === i ? "atual" : "futuro";
  });
}

function enviarArquivo(arquivo) {
  const erro = $("erro-upload");
  erro.classList.add("hidden");
  erro.classList.remove("escaneado");

  // Recusa antes de subir: erra rápido e não gasta a viagem.
  if (!/\.pdf$/i.test(arquivo.name) && arquivo.type !== "application/pdf") {
    erro.textContent = "Só PDF nesta fase.";
    erro.classList.remove("hidden");
    return;
  }

  $("carregando-upload").classList.remove("hidden");
  $("zona").classList.add("hidden");
  $("progresso-titulo").textContent = "Enviando o arquivo…";
  $("progresso-sub").textContent = `${arquivo.name} · ${formatarTamanho(arquivo.size)}`;
  $("envio-pct").textContent = "";
  marcarEtapaUpload("etapa-envio");

  const corpo = new FormData();
  corpo.append("arquivo", arquivo);

  // XHR e não fetch: é o único jeito de ter progresso real do envio.
  const xhr = new XMLHttpRequest();
  xhr.open("POST", "/api/doc");
  xhr.upload.addEventListener("progress", (e) => {
    if (e.lengthComputable) {
      $("envio-pct").textContent = `${Math.round((100 * e.loaded) / e.total)}%`;
    }
  });
  xhr.upload.addEventListener("load", () => {
    marcarEtapaUpload("etapa-deteccao");
    $("progresso-titulo").textContent = "Extraindo texto e detectando dados…";
  });

  const terminar = () => {
    $("carregando-upload").classList.add("hidden");
    $("arquivo").value = "";
  };
  const falhar = (mensagem, escaneado = false) => {
    terminar();
    if (escaneado) {
      erro.classList.add("escaneado");
      erro.innerHTML =
        "<strong>Este PDF não tem texto selecionável.</strong>" +
        "Provavelmente é uma digitalização. A detecção depende de OCR, que " +
        "ainda não existe nesta ferramenta — nada foi processado nem guardado.";
    } else {
      erro.textContent = mensagem;
    }
    erro.classList.remove("hidden");
    $("zona").classList.remove("hidden");
  };

  xhr.addEventListener("load", () => {
    let dados = null;
    try {
      dados = JSON.parse(xhr.responseText);
    } catch {
      /* resposta sem JSON: cai na mensagem genérica abaixo */
    }
    if (xhr.status !== 200 || !dados) {
      const detalhe = (dados && dados.detail) || "falha no envio";
      return falhar(detalhe, xhr.status === 422 && /escaneado/i.test(detalhe));
    }
    marcarEtapaUpload("etapa-pronto");
    terminar();
    doc = dados;
    estado.exportou = false;
    lembrarSessao(doc.doc_id);
    montarRevisao();
  });
  xhr.addEventListener("error", () => falhar("não foi possível falar com o servidor"));
  xhr.send(corpo);
}

function formatarTamanho(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

// Qual modelo está detectando — muda o que esperar da revisão, e muda o que o
// aviso de envio externo pode afirmar sobre nomes que escapam.
let nerAtivo = null;
fetch("/api/saude")
  .then((r) => (r.ok ? r.json() : null))
  .then((d) => {
    if (d) {
      nerAtivo = d.ner;
      $("modelo-ativo").textContent =
        `Detecção por ${d.ner}, ${d.entidades} tipos de dado.`;
    }
  })
  .catch(() => {});

// O **envio** a modelo externo só é oferecido se o serviço `analise` está no
// ar e tem chave. Com `make ui` ele não sobe, e um botão que só devolve erro
// seria promessa sem executor. Gerar e ler o texto não depende disso.
let analiseDisponivel = false;
let analiseMotivo = "verificando o serviço de análise…";
fetch("/api/analise/saude")
  .then((r) => (r.ok ? r.json() : null))
  .then((d) => {
    analiseDisponivel = Boolean(d && d.disponivel);
    analiseMotivo = (d && d.motivo) || "serviço de análise não respondeu";
    if (analiseDisponivel) $("analise-modelo").textContent = d.modelo || "";
    if (doc) sincronizarAnalise();
  })
  .catch(() => {
    analiseMotivo = "serviço de análise não respondeu";
  });

/* ------------------------------------------------ sessão entre recargas ---
 *
 * A revisão vive no servidor; o navegador só guarda qual é. Sem isto, um F5
 * acidental jogava fora todo o trabalho de revisão — as tarjas desligadas, os
 * trechos apontados à mão — enquanto a sessão continuava lá, intacta e
 * inalcançável.
 *
 * Só identificadores são guardados: o da sessão e, por conveniência, os ids
 * dos trechos já visitados (`s12`, nunca o valor). Nenhum conteúdo de
 * documento passa pelo armazenamento do navegador.
 */
const CHAVE_SESSAO = "anonimizador.doc";
const PREFIXO_REVISADOS = "anonimizador.revisados.";

function lembrarSessao(id) {
  try {
    localStorage.setItem(CHAVE_SESSAO, id);
  } catch {
    /* modo privado, cota cheia: perder a retomada não pode quebrar a tela */
  }
}

function esquecerSessao() {
  try {
    const id = localStorage.getItem(CHAVE_SESSAO);
    localStorage.removeItem(CHAVE_SESSAO);
    if (id) localStorage.removeItem(PREFIXO_REVISADOS + id);
  } catch {}
}

function lerRevisados(doc_id) {
  try {
    const bruto = localStorage.getItem(PREFIXO_REVISADOS + doc_id);
    const ids = bruto ? JSON.parse(bruto) : [];
    return new Set(Array.isArray(ids) ? ids.filter((x) => typeof x === "string") : []);
  } catch {
    return new Set();
  }
}

function guardarRevisados() {
  if (!doc) return;
  try {
    localStorage.setItem(PREFIXO_REVISADOS + doc.doc_id, JSON.stringify([...estado.revisados]));
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
    estado.exportou = null; // não dá para saber o que foi baixado antes do F5
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
  $("etapas").classList.remove("hidden");
  $("topo-acoes").classList.remove("hidden");
  $("nome-arquivo").textContent = doc.nome_arquivo;
  $("btn-arquivo").title = doc.nome_arquivo;
  document.title = `${doc.nome_arquivo} — Anonimizador`;

  estado.revisados = lerRevisados(doc.doc_id);
  estado.previa = null;
  estado.focado = null;
  estado.sucesso = false;
  estado.expandidas = new Set();
  // Abre a primeira categoria com algo marcado: é por ela que a revisão
  // costuma começar, e a lista vazia não ensina nada.
  const primeira = doc.spans.find((s) => s.sera_tarjado);
  if (primeira) estado.expandidas.add(primeira.entity);

  montarPaginas($("coluna-original"), false);
  montarPaginas($("coluna-anonimizado"), true);
  montarMiniaturas();
  aplicarVista(estado.vista);
  selecionarAba("deteccoes");
  redesenhar();
  agendarPreverificacao(0);
}

function montarPaginas(container, comTarjas) {
  container.innerHTML = "";
  const cabeca = document.createElement("div");
  cabeca.className = "cabeca-coluna";
  cabeca.textContent = comTarjas ? "Anonimizado" : "Original";
  container.appendChild(cabeca);

  for (const p of doc.paginas) {
    const div = document.createElement("div");
    div.className = "pagina";
    div.dataset.n = p.numero;
    // A altura existe antes de a imagem carregar: rolar até uma página ou
    // uma ocorrência funciona mesmo com as imagens ainda chegando.
    div.style.aspectRatio = `${p.largura} / ${p.altura}`;

    const img = document.createElement("img");
    img.src = `/api/doc/${doc.doc_id}/pagina/${p.numero}.png?escala=${ESCALA}`;
    img.alt = `${comTarjas ? "Anonimizado" : "Original"}, página ${p.numero + 1}`;
    img.loading = "lazy";
    div.appendChild(img);

    if (comTarjas) {
      // Camada de texto selecionável **só na coluna Anonimizado**: você
      // seleciona o que *ainda* está legível e manda anonimizar, no mesmo
      // lugar em que vê o efeito.
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
 * do container. A camada inteira ficava microscópica: o realce da seleção era
 * invisível, e o `scaleX` de correção esticava cada palavra por cima da linha
 * inteira, de modo que a seleção pegava muito mais do que o apontado.
 *
 * O tamanho tem de ser calculado em pixels, a partir da altura **renderizada**
 * da página — que só se conhece depois de a imagem carregar, e muda com o
 * zoom e com a janela. Daí o `ResizeObserver`. */
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
    // que o navegador selecionou e o que o servidor vai anonimizar: somado ao
    // deslocamento dentro do nó de texto, dá o caractere exato.
    s.dataset.i = p.i;
    frag.appendChild(s);
  }
  camada.appendChild(frag);

  const ajustar = () => ajustarCamadaDeTexto(camada, pagina);
  ajustar();

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
    s.style.transform = "none";
    s.style.fontSize = Number(s.dataset.alturaPt) * pxPorPontoV + "px";
  }

  // A medição de largura precisa acontecer depois de todos os tamanhos já
  // aplicados — lê-la no mesmo laço forçaria um reflow por palavra.
  for (const s of camada.children) {
    const alvoPx = Number(s.dataset.larguraPt) * pxPorPontoH;
    const real = s.getBoundingClientRect().width;
    // A fonte do sistema quase nunca tem a mesma largura da fonte embutida no
    // PDF; o scaleX faz a caixa do texto coincidir com o que a imagem mostra.
    if (real > 0.5 && alvoPx > 0) {
      s.style.transform = `scaleX(${alvoPx / real})`;
    }
  }
}

// ------------------------------------------------------------ miniaturas
function montarMiniaturas() {
  const caixa = $("miniaturas");
  caixa.innerHTML = "";
  for (const p of doc.paginas) {
    const b = document.createElement("button");
    b.className = "miniatura";
    b.dataset.n = p.numero;
    b.setAttribute("aria-label", `Ir para a página ${p.numero + 1}`);
    b.style.aspectRatio = `${p.largura} / ${p.altura}`;

    const img = document.createElement("img");
    img.src = `/api/doc/${doc.doc_id}/pagina/${p.numero}.png?escala=${ESCALA_MINIATURA}`;
    img.alt = "";
    img.loading = "lazy";

    const contagem = document.createElement("span");
    contagem.className = "contagem";

    const numero = document.createElement("span");
    numero.className = "numero-pagina";
    numero.textContent = p.numero + 1;

    b.append(img, contagem, numero);
    b.addEventListener("click", () => irParaPagina(p.numero + 1));
    caixa.appendChild(b);
  }
}

function atualizarMiniaturas() {
  const ativos = new Map();
  for (const s of doc.spans) {
    if (!s.sera_tarjado) continue;
    for (const pg of new Set(s.rects.map((r) => r.pagina))) {
      ativos.set(pg, (ativos.get(pg) || 0) + 1);
    }
  }
  const pendentes = new Set();
  for (const o of pendenciasLegiveis()) for (const n of o.paginas || []) pendentes.add(n - 1);

  for (const b of $("miniaturas").children) {
    const n = Number(b.dataset.n);
    const c = b.querySelector(".contagem");
    const qtd = ativos.get(n) || 0;
    c.textContent = pendentes.has(n) ? "!" : qtd;
    c.className =
      "contagem" + (pendentes.has(n) ? " pendente" : qtd === 0 ? " zero" : "");
    b.title = pendentes.has(n)
      ? `Página ${n + 1}: há dado marcado ainda legível aqui`
      : `Página ${n + 1}: ${qtd} ${qtd === 1 ? "dado ativo" : "dados ativos"}`;
  }
}

/* Página atual: a que ocupa o meio da área visível. */
let rafRolagem = 0;
$("rolagem").addEventListener("scroll", () => {
  esconderDica();
  fecharPopovers();
  if (rafRolagem) return;
  rafRolagem = requestAnimationFrame(() => {
    rafRolagem = 0;
    atualizarPaginaAtual();
  });
});

function colunaVisivel() {
  return estado.vista === "original" ? $("coluna-original") : $("coluna-anonimizado");
}

function atualizarPaginaAtual() {
  if (!doc) return;
  const rol = $("rolagem");
  const meio = rol.getBoundingClientRect().top + rol.clientHeight / 2;
  let atual = 0;
  for (const p of colunaVisivel().querySelectorAll(".pagina")) {
    if (p.getBoundingClientRect().top <= meio) atual = Number(p.dataset.n);
  }
  $("indicador-pagina").textContent = `${atual + 1} / ${doc.paginas.length}`;
  for (const b of $("miniaturas").children) {
    const eh = Number(b.dataset.n) === atual;
    b.setAttribute("aria-current", eh ? "true" : "false");
    if (eh && b.scrollIntoViewIfNeeded) b.scrollIntoViewIfNeeded(false);
  }
}

/* `n` como o servidor e o rótulo contam: a partir de 1. `data-n` guarda o
 * índice a partir de 0, que é o da rota de imagem. */
function irParaPagina(n) {
  if (estado.vista === "original") aplicarVista("anonimizado");
  const alvo = colunaVisivel().querySelector(`.pagina[data-n="${n - 1}"]`);
  alvo?.scrollIntoView({ behavior: "smooth", block: "start" });
  fecharInspetorEstreito();
}

// ------------------------------------------------------- vista e zoom
for (const b of document.querySelectorAll("[data-vista]")) {
  b.addEventListener("click", () => aplicarVista(b.dataset.vista));
}

function aplicarVista(vista) {
  if (vista === "comparar" && telaEstreita.matches) vista = "anonimizado";
  estado.vista = vista;
  const col = $("colunas");
  col.classList.remove("vista-anonimizado", "vista-original", "vista-comparar");
  col.classList.add(`vista-${vista}`);
  for (const b of document.querySelectorAll("[data-vista]")) {
    b.setAttribute("aria-pressed", String(b.dataset.vista === vista));
  }
  // "Ver como ficará" só faz sentido onde há marcações.
  $("btn-previa").disabled = vista === "original";
  aplicarLargura();
  atualizarPaginaAtual();
}

$("btn-previa").addEventListener("click", () => alternarPreviaFinal());

function alternarPreviaFinal(valor) {
  estado.previaFinal = valor === undefined ? !estado.previaFinal : valor;
  $("btn-previa").setAttribute("aria-pressed", String(estado.previaFinal));
  $("colunas").classList.toggle("final", estado.previaFinal);
}

const ZOOMS = [0.5, 0.67, 0.8, 0.9, 1, 1.1, 1.25, 1.5, 1.75, 2];

function mudarZoom(delta) {
  const i = ZOOMS.findIndex((z) => z >= estado.zoom - 1e-6);
  const j = Math.max(0, Math.min(ZOOMS.length - 1, (i === -1 ? 4 : i) + delta));
  const rol = $("rolagem");
  // Mantém o mesmo ponto do documento no meio da tela depois do zoom.
  const proporcao = (rol.scrollTop + rol.clientHeight / 2) / Math.max(1, rol.scrollHeight);
  estado.zoom = ZOOMS[j];
  aplicarLargura();
  rol.scrollTop = proporcao * rol.scrollHeight - rol.clientHeight / 2;
}
$("btn-zoom-mais").addEventListener("click", () => mudarZoom(1));
$("btn-zoom-menos").addEventListener("click", () => mudarZoom(-1));

/* Largura da página: a de leitura confortável, não a da janela inteira. No
 * modo comparar, as duas colunas dividem o espaço — e rolam juntas porque
 * estão no mesmo contêiner de rolagem, com o mesmo zoom, por construção. */
function aplicarLargura() {
  const rol = $("rolagem");
  if (!rol.clientWidth) return;
  const disponivel = rol.clientWidth - 48;
  const base =
    estado.vista === "comparar"
      ? Math.min((disponivel - 24) / 2, 720)
      : Math.min(disponivel, 840);
  const largura = Math.max(220, Math.round(base * estado.zoom));
  $("colunas").style.setProperty("--largura-pagina", `${largura}px`);
  $("zoom-valor").textContent = `${Math.round(estado.zoom * 100)}%`;
}

if (window.ResizeObserver) new ResizeObserver(() => aplicarLargura()).observe($("rolagem"));

// ------------------------------------------------------------ redesenho
/* O que aparece no documento.
 *
 * Categoria desligada não desenha nada: contorno tracejado em "MINISTÉRIO DOS"
 * e "DNIT" era ruído, e sugeria que a ferramenta ia mexer ali. O que continua
 * visível sem preenchimento é o trecho que o revisor mandou **não**
 * anonimizar numa categoria ligada — ele precisa ver o que recusou, e poder
 * desfazer com um clique.
 *
 * Fragmento de palavra ("RO" dentro de "RODOVIÁRIA") é defeito do detector.
 * Quando ele não vai sair do documento, não é desenhado. Quando **vai** sair,
 * é desenhado mesmo assim: esconder da tela algo que o PDF vai remover faria
 * a tela mentir sobre o arquivo — o pior dos três modos de falha. */
const fragmentosAvisados = new Set();

function visivelNoDocumento(s) {
  if (s.fragmento && !fragmentosAvisados.has(s.id)) {
    fragmentosAvisados.add(s.id);
    console.warn(
      `[anonimizador] trecho ${s.id} (${s.entity}) começa ou termina no meio de ` +
        `uma palavra — defeito de detecção a corrigir` +
        (s.sera_tarjado ? "; desenhado porque vai sair do PDF" : "; não desenhado")
    );
  }
  if (s.sera_tarjado) return true;
  if (s.fragmento) return false;
  return s.origem === "usuario" || s.ativo === false;
}

function ordemDeLeitura(a, b) {
  const ra = a.rects[0];
  const rb = b.rects[0];
  if (!ra || !rb) return ra ? -1 : rb ? 1 : 0;
  return ra.pagina - rb.pagina || ra.y0 - rb.y0 || ra.x0 - rb.x0;
}

/* As ocorrências que a navegação percorre, na ordem de leitura. */
function navegaveis() {
  return doc.spans.filter((s) => visivelNoDocumento(s) && s.rects.length).sort(ordemDeLeitura);
}

function redesenhar() {
  desenharMarcacoes();
  montarResumo();
  montarCategorias();
  atualizarMiniaturas();
  sincronizarModo();
  sincronizarAnalise();
  atualizarVerificacao();
  montarAvisos();
  atualizarSaidas();
}

function destinoDe(s) {
  if (!s.sera_tarjado) return "não será anonimizado";
  if (s.token) return `vira ${s.token}`;
  if (s.sem_token) return "tarja preta — o código não cabe neste espaço";
  return "tarja preta";
}

/* Desenha as marcações a partir do estado do servidor.
 * Coordenadas chegam em pontos de PDF; a página tem largura/altura em pontos.
 * Converter para porcentagem torna o posicionamento independente do zoom, do
 * tamanho da janela e de a imagem ter carregado ou não. */
function desenharMarcacoes() {
  const camadas = $("coluna-anonimizado").querySelectorAll(".camada-tarjas");
  camadas.forEach((c) => (c.innerHTML = ""));

  for (const s of doc.spans) {
    if (!visivelNoDocumento(s)) continue;
    const cat = categoria(s.entity);
    for (const [i, r] of s.rects.entries()) {
      const pagina = doc.paginas[r.pagina];
      const camada = camadas[r.pagina];
      if (!pagina || !camada) continue;

      const caixa = document.createElement("span");
      caixa.className = `tarja cat-${cat.cor}`;
      if (!s.sera_tarjado) caixa.classList.add("desligada");
      if (s.origem === "usuario") caixa.classList.add("manual");
      if (s.id === estado.focado) caixa.classList.add("focada");
      /* Código no lugar: em "Ver como ficará" a caixa fica branca e o código
       * aparece só na primeira caixa do trecho (um valor que quebra a linha
       * tem duas, e repetir o código faria enxergar dois atores). O corpo sai
       * da altura da caixa pelo mesmo fator do redator (`FATOR_CORPO`), em
       * `cqw` da camada, para acompanhar o zoom sem recalcular.
       *
       * `s.token` vem do servidor e já considera a largura: onde o código não
       * cabe ele é nulo e a caixa continua tarja, como no PDF. */
      if (s.sera_tarjado && s.token) {
        caixa.classList.add("codigo");
        if (i === 0) {
          const rot = document.createElement("span");
          rot.className = "rotulo-codigo";
          rot.textContent = s.token;
          caixa.appendChild(rot);
          const corpoPt = (r.y1 - r.y0) * 0.728;
          caixa.style.fontSize = `${(100 * corpoPt) / pagina.largura}cqw`;
        }
      }
      // Detectado pela forma, não pelo dígito verificador. É palpite forte,
      // não certeza matemática, e o revisor precisa saber a diferença.
      if (s.nota === "checksum_invalido") caixa.classList.add("suspeita");
      caixa.style.left = (100 * r.x0) / pagina.largura + "%";
      caixa.style.top = (100 * r.y0) / pagina.altura + "%";
      caixa.style.width = (100 * (r.x1 - r.x0)) / pagina.largura + "%";
      caixa.style.height = (100 * (r.y1 - r.y0)) / pagina.altura + "%";

      caixa.dataset.spanId = s.id;
      caixa.setAttribute("role", "button");
      caixa.tabIndex = -1;
      caixa.setAttribute("aria-label", `${cat.singular}: ${destinoDe(s)}`);

      /* Clique na marcação abre as ações. O que elas oferecem depende de
       * quem criou o trecho — ver `acoesDaMarca`. */
      caixa.addEventListener("click", (ev) => {
        ev.stopPropagation();
        focar(s.id, { rolar: false });
        abrirPopoverMarca(s, caixa);
      });
      caixa.addEventListener("mouseenter", () => mostrarDica(s, caixa));
      caixa.addEventListener("mouseleave", esconderDica);
      camada.appendChild(caixa);
    }
  }
}

// ------------------------------------------------------ dica e popover
const dica = $("dica");

function mostrarDica(s, caixa) {
  const cat = categoria(s.entity);
  dica.innerHTML = "";
  const nome = document.createElement("strong");
  nome.textContent = cat.singular;
  const valor = document.createElement("span");
  valor.className = "valor-dica";
  valor.textContent = s.valor.length > 60 ? s.valor.slice(0, 60) + "…" : s.valor;
  const seta = document.createElement("span");
  seta.className = "seta";
  seta.textContent = " → ";
  const destino = document.createElement("span");
  destino.textContent = s.sera_tarjado ? (s.token ? s.token : "tarja preta") : "não será anonimizado";
  dica.append(nome, document.createTextNode(" · "), valor, seta, destino);
  if (s.sem_token) dica.append(document.createTextNode(" (o código não cabe)"));
  if (s.nota === "checksum_invalido") {
    dica.append(
      document.createElement("br"),
      document.createTextNode("Forma válida, dígito verificador inválido — confira.")
    );
  }
  const r = caixa.getBoundingClientRect();
  dica.classList.remove("hidden");
  const d = dica.getBoundingClientRect();
  const left = Math.max(8, Math.min(window.innerWidth - d.width - 8, r.left + r.width / 2 - d.width / 2));
  const acima = r.top - d.height - 8;
  dica.style.left = `${left}px`;
  dica.style.top = `${acima > 60 ? acima : r.bottom + 8}px`;
}

function esconderDica() {
  dica.classList.add("hidden");
}

const popoverMarca = $("popover-marca");

function iguaisA(s) {
  const chave = normalizarValor(s.valor);
  return doc.spans.filter((x) => normalizarValor(x.valor) === chave && (x.origem === "usuario") === (s.origem === "usuario"));
}

/* As ações sobre uma marcação.
 *
 * Proposta do detector -> **não anonimizar** (desliga). O retângulo continua
 * ali, sem preenchimento: o revisor precisa enxergar o que o sistema achou e
 * ele recusou; fazer sumir esconderia justamente o que torna a revisão
 * auditável.
 *
 * Trecho que o usuário adicionou -> **remove**. Ele não propôs nada, ele
 * mandou anonimizar; desfazer é apagar. Desligar deixava um retângulo no
 * lugar, e a leitura correta disso é "não saiu". */
function acoesDaMarca(s) {
  const acoes = [];
  const iguais = iguaisA(s);
  if (s.origem === "usuario") {
    acoes.push({ rotulo: "Remover este trecho", fazer: () => removerSpan(s.id), perigo: true });
    if (iguais.length > 1) {
      acoes.push({
        rotulo: `Remover todos iguais (${iguais.length})`,
        fazer: () => removerVarios(iguais.map((x) => x.id)),
        perigo: true,
      });
    }
    return acoes;
  }
  if (s.sera_tarjado) {
    acoes.push({ rotulo: "Não anonimizar esta", fazer: () => alternar(s.id, false) });
    if (iguais.length > 1) {
      acoes.push({
        rotulo: `Não anonimizar nenhuma igual (${iguais.length})`,
        fazer: () => alternarIguais(s.id, false),
      });
    }
  } else {
    acoes.push({ rotulo: "Anonimizar esta", fazer: () => alternar(s.id, true) });
    if (iguais.length > 1) {
      acoes.push({
        rotulo: `Anonimizar todas iguais (${iguais.length})`,
        fazer: () => alternarIguais(s.id, true),
      });
    }
  }
  return acoes;
}

function abrirPopoverMarca(s, ancora) {
  esconderDica();
  fecharPopovers();
  const cat = categoria(s.entity);
  popoverMarca.innerHTML = "";

  const cabeca = document.createElement("div");
  cabeca.className = "cabeca-popover";
  const nome = document.createElement("strong");
  nome.textContent = cat.singular;
  const valor = document.createElement("span");
  valor.className = "valor-popover";
  valor.textContent = s.valor;
  const destino = document.createElement("span");
  destino.className = "destino";
  destino.textContent = destinoDe(s);
  cabeca.append(nome, document.createTextNode(" · "), destino, valor);
  popoverMarca.appendChild(cabeca);

  for (const a of acoesDaMarca(s)) {
    const b = document.createElement("button");
    b.className = "acao" + (a.perigo ? " perigo-texto" : "");
    b.textContent = a.rotulo;
    b.addEventListener("click", async () => {
      fecharPopovers();
      await executar(a.fazer);
    });
    popoverMarca.appendChild(b);
  }

  // Mudar categoria: só para o que o detector achou. Trecho apontado à mão
  // não tem classe, e o servidor recusa.
  if (s.origem !== "usuario") {
    const rotulo = document.createElement("label");
    rotulo.className = "acao";
    rotulo.textContent = "Mudar categoria";
    rotulo.htmlFor = "mudar-categoria";
    const sel = document.createElement("select");
    sel.id = "mudar-categoria";
    for (const ent of doc.entidades_ativas || Object.keys(CATEGORIAS)) {
      if (ent === "MANUAL") continue;
      const o = document.createElement("option");
      o.value = ent;
      o.textContent = categoria(ent).nome;
      o.selected = ent === s.entity;
      sel.appendChild(o);
    }
    sel.addEventListener("change", async () => {
      fecharPopovers();
      await executar(() => mudarEntidade(s.id, sel.value));
    });
    popoverMarca.append(rotulo, sel);
  }

  posicionarFlutuante(popoverMarca, ancora.getBoundingClientRect());
  popoverMarca.querySelector("button, select")?.focus();
}

function posicionarFlutuante(el, r) {
  el.classList.remove("hidden");
  const d = el.getBoundingClientRect();
  const left = Math.max(8, Math.min(window.innerWidth - d.width - 8, r.left));
  const abaixo = r.bottom + 6;
  const top = abaixo + d.height < window.innerHeight - 8 ? abaixo : Math.max(64, r.top - d.height - 6);
  el.style.left = `${left}px`;
  el.style.top = `${top}px`;
}

function fecharPopovers() {
  popoverMarca.classList.add("hidden");
  $("popover-atalhos").classList.add("hidden");
  $("btn-atalhos").setAttribute("aria-expanded", "false");
  fecharMenuArquivo();
}

document.addEventListener("mousedown", (e) => {
  if (!e.target.closest(".popover, .menu, #btn-arquivo, #btn-atalhos, .tarja")) {
    popoverMarca.classList.add("hidden");
    $("popover-atalhos").classList.add("hidden");
    fecharMenuArquivo();
  }
});

// ------------------------------------------------------------- navegação
function marcarRevisado(id) {
  if (!estado.revisados.has(id)) {
    estado.revisados.add(id);
    guardarRevisados();
  }
}

/* Leva o documento até a ocorrência, destaca e marca como revisada. */
function focar(id, { rolar = true, piscar = true } = {}) {
  const s = doc.spans.find((x) => x.id === id);
  if (!s) return;
  estado.focado = id;
  marcarRevisado(id);
  if (estado.vista === "original") aplicarVista("anonimizado");

  const caixas = $("coluna-anonimizado").querySelectorAll(".tarja");
  let primeira = null;
  for (const c of caixas) {
    const eh = c.dataset.spanId === id;
    c.classList.toggle("focada", eh);
    c.classList.remove("piscar");
    if (eh && !primeira) primeira = c;
  }
  if (primeira) {
    if (rolar) primeira.scrollIntoView({ behavior: "smooth", block: "center" });
    if (piscar) {
      void primeira.offsetWidth; // reinicia a animação
      primeira.classList.add("piscar");
    }
    primeira.focus({ preventScroll: true });
  }
  montarResumo();
  destacarNaLista(id);
}

function passo(delta) {
  const lista = navegaveis();
  if (!lista.length) return;
  let i = lista.findIndex((s) => s.id === estado.focado);
  i = i === -1 ? (delta > 0 ? 0 : lista.length - 1) : (i + delta + lista.length) % lista.length;
  focar(lista[i].id);
  fecharInspetorEstreito();
}
$("btn-proximo").addEventListener("click", () => passo(1));
$("btn-anterior").addEventListener("click", () => passo(-1));

// --------------------------------------------------------------- resumo
function montarResumo() {
  const ativos = doc.spans.filter((s) => s.sera_tarjado);
  const paginas = new Set();
  for (const s of ativos) for (const r of s.rects) paginas.add(r.pagina);
  $("resumo-deteccoes").textContent = ativos.length
    ? `${ativos.length} ${ativos.length === 1 ? "dado será anonimizado" : "dados serão anonimizados"} ` +
      `em ${paginas.size} ${paginas.size === 1 ? "página" : "páginas"}`
    : "Nenhum dado marcado para anonimizar";

  const revisados = ativos.filter((s) => estado.revisados.has(s.id)).length;
  const pct = ativos.length ? (100 * revisados) / ativos.length : 0;
  $("barra-revisao-cheia").style.width = `${pct}%`;
  $("barra-revisao").setAttribute("aria-valuemax", String(ativos.length));
  $("barra-revisao").setAttribute("aria-valuenow", String(revisados));
  $("texto-revisao").textContent = ativos.length ? `${revisados} de ${ativos.length} revisados` : "";
  const temNavegacao = navegaveis().length > 0;
  $("btn-proximo").disabled = !temNavegacao;
  $("btn-anterior").disabled = !temNavegacao;

  $("vazio-deteccoes").classList.toggle("hidden", doc.spans.length > 0);
}

// ------------------------------------------------------------ categorias
function normalizarValor(v) {
  return v.split(/\s+/).filter(Boolean).join(" ");
}

function semAcento(v) {
  return v.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
}

/* Agrupa os trechos de uma categoria por valor, na ordem de leitura. */
function gruposPorValor(spans) {
  const mapa = new Map();
  for (const s of [...spans].sort(ordemDeLeitura)) {
    const chave = normalizarValor(s.valor);
    if (!mapa.has(chave)) mapa.set(chave, []);
    mapa.get(chave).push(s);
  }
  return mapa;
}

/* Inventário.
 *
 * Mostra **todas** as entidades que a política cobre, inclusive as que não
 * apareceram. Listar só o que foi detectado fazia "procurei e não há" parecer
 * igual a "não sei procurar" — as duas somem da tela do mesmo jeito, e a
 * leitura natural é a segunda. Com a linha zerada visível, o usuário vê que a
 * ferramenta olhou. */
function montarCategorias() {
  const caixa = $("lista-categorias");
  const rolagem = $("painel-deteccoes").scrollTop;
  caixa.innerHTML = "";

  const porEntidade = new Map();
  for (const ent of Object.keys(doc.inventario || {})) porEntidade.set(ent, []);
  porEntidade.set("MANUAL", porEntidade.get("MANUAL") || []);
  for (const s of doc.spans) {
    if (!porEntidade.has(s.entity)) porEntidade.set(s.entity, []);
    porEntidade.get(s.entity).push(s);
  }

  for (const g of GRUPOS) {
    const entidades = [...porEntidade.keys()]
      .filter((e) => categoria(e).grupo === g.id)
      .sort((a, b) => {
        const ordem = Object.keys(CATEGORIAS);
        const ia = ordem.indexOf(a);
        const ib = ordem.indexOf(b);
        return (ia === -1 ? 99 : ia) - (ib === -1 ? 99 : ib);
      });
    if (!entidades.length) continue;

    const bloco = document.createElement("section");
    bloco.className = "grupo-categorias";
    const titulo = document.createElement("h2");
    titulo.className = "rotulo-grupo";
    titulo.textContent = g.id === "contexto" ? `${g.rotulo} · preservados por padrão` : g.rotulo;
    bloco.appendChild(titulo);

    for (const ent of entidades) bloco.appendChild(linhaCategoria(ent, porEntidade.get(ent)));
    caixa.appendChild(bloco);
  }
  $("painel-deteccoes").scrollTop = rolagem;
  if (estado.focado) destacarNaLista(estado.focado);
}

function linhaCategoria(entidade, spans) {
  const cat = categoria(entidade);
  const total = spans.length;
  const ativos = spans.filter((s) => s.sera_tarjado).length;
  const vazia = total === 0;
  const aberta = estado.expandidas.has(entidade) && !vazia;

  const embrulho = document.createElement("div");
  const linha = document.createElement("div");
  linha.className = `linha-categoria cat-${cat.cor}` + (vazia ? " vazia" : "");

  const chk = document.createElement("input");
  chk.type = "checkbox";
  chk.checked = total > 0 && ativos === total;
  chk.indeterminate = ativos > 0 && ativos < total;
  chk.disabled = vazia;
  chk.setAttribute(
    "aria-label",
    vazia
      ? `${cat.nome}: nenhuma ocorrência neste documento`
      : `Anonimizar ${cat.nome}`
  );
  // `MANUAL` não é entidade de política — é origem —, então tem caminho
  // próprio no servidor. Mexer no perfil dela seria recusado, com razão.
  chk.addEventListener("change", () =>
    executar(() =>
      entidade === "MANUAL" ? alternarManuais(chk.checked) : alternarEntidade(entidade, chk.checked)
    )
  );

  const bolinha = document.createElement("span");
  bolinha.className = "bolinha";
  bolinha.setAttribute("aria-hidden", "true");

  const nome = document.createElement("span");
  nome.className = "nome-categoria";
  nome.textContent = cat.nome;

  const qtd = document.createElement("span");
  qtd.className = "contagem-categoria";
  qtd.textContent = vazia
    ? entidade === "MANUAL" ? "nenhum" : "nenhuma"
    : `${ativos} de ${total}`;
  if (!vazia) qtd.title = `${ativos} serão anonimizadas, de ${total} encontradas`;

  const expandir = document.createElement("button");
  expandir.className = "expandir";
  expandir.disabled = vazia;
  expandir.setAttribute("aria-expanded", String(aberta));
  expandir.setAttribute("aria-label", `${aberta ? "Recolher" : "Mostrar"} ocorrências de ${cat.nome}`);
  expandir.innerHTML = icone("chevron");
  const alternarAberta = () => {
    if (vazia) return;
    if (estado.expandidas.has(entidade)) estado.expandidas.delete(entidade);
    else estado.expandidas.add(entidade);
    montarCategorias();
  };
  expandir.addEventListener("click", alternarAberta);
  nome.addEventListener("click", alternarAberta);

  linha.append(chk, bolinha, nome, qtd, expandir);
  embrulho.appendChild(linha);

  if (entidade === "MANUAL" && vazia) {
    const dicaVazia = document.createElement("p");
    dicaVazia.className = "auxiliar";
    dicaVazia.style.margin = "0 0 0 28px";
    dicaVazia.textContent = "Use a busca acima ou selecione um trecho no documento.";
    embrulho.appendChild(dicaVazia);
  }

  if (aberta) embrulho.appendChild(listaOcorrencias(entidade, spans));
  return embrulho;
}

function listaOcorrencias(entidade, spans) {
  const ul = document.createElement("ul");
  ul.className = "ocorrencias";
  for (const [valor, grupo] of gruposPorValor(spans)) {
    const li = document.createElement("li");
    const ligados = grupo.filter((s) => s.sera_tarjado).length;
    if (!ligados) li.classList.add("desligada");
    if (grupo.every((s) => estado.revisados.has(s.id))) li.classList.add("revisada");
    li.dataset.ids = grupo.map((s) => s.id).join(" ");

    const ir = document.createElement("button");
    ir.className = "ir";
    ir.title = "Mostrar no documento";
    const v = document.createElement("span");
    v.className = "valor";
    v.textContent = valor;
    const paginas = [...new Set(grupo.flatMap((s) => s.rects.map((r) => r.pagina + 1)))].sort((a, b) => a - b);
    const onde = document.createElement("span");
    onde.className = "onde";
    onde.textContent =
      `${grupo.length}× · ` + (paginas.length ? `p. ${paginas.join(", ")}` : "sem região visível");
    ir.append(v, onde);
    if (grupo.some((s) => s.nota === "checksum_invalido")) {
      const n = document.createElement("span");
      n.className = "suspeita-nota";
      n.textContent = "forma válida, dígito verificador inválido — confira";
      ir.appendChild(n);
    }
    // Cada clique leva à próxima aparição do valor.
    ir.addEventListener("click", () => {
      const k = estado.cicloGrupo.get(valor) || 0;
      const alvo = grupo[k % grupo.length];
      estado.cicloGrupo.set(valor, k + 1);
      if (visivelNoDocumento(alvo)) focar(alvo.id);
      else marcarRevisado(alvo.id);
      fecharInspetorEstreito();
    });

    const chk = document.createElement("input");
    chk.type = "checkbox";
    chk.checked = ligados === grupo.length;
    chk.indeterminate = ligados > 0 && ligados < grupo.length;
    chk.setAttribute("aria-label", `Anonimizar ${valor}`);
    chk.addEventListener("change", () =>
      executar(async () => {
        grupo.forEach((s) => marcarRevisado(s.id));
        if (entidade === "MANUAL") {
          for (const s of grupo) await alternar(s.id, chk.checked, false);
          aposEdicao();
        } else {
          await alternarIguais(grupo[0].id, chk.checked);
        }
      })
    );

    li.append(ir, chk);

    // Trecho apontado à mão: apagar de vez. Um termo digitado errado espalha
    // marcações pelo documento; aqui elas saem todas de uma vez.
    if (entidade === "MANUAL") {
      const del = document.createElement("button");
      del.className = "apagar";
      del.innerHTML = icone("lixeira");
      del.setAttribute("aria-label", `Apagar ${valor} da proposta`);
      del.title = "Apagar estes trechos da proposta";
      del.addEventListener("click", () => executar(() => removerVarios(grupo.map((s) => s.id))));
      li.appendChild(del);
    } else {
      li.appendChild(document.createElement("span"));
    }
    ul.appendChild(li);
  }
  return ul;
}

function destacarNaLista(id) {
  for (const li of $("lista-categorias").querySelectorAll(".ocorrencias li")) {
    const eh = li.dataset.ids.split(" ").includes(id);
    li.classList.toggle("em-foco", eh);
    if (eh && estado.aba === "deteccoes") li.scrollIntoView({ block: "nearest" });
  }
}

// ----------------------------------------------------------------- edição
async function enviar(caminho, opcoes) {
  const r = await fetch(`/api/doc/${doc.doc_id}${caminho}`, opcoes);
  const dados = await r.json();
  if (!r.ok) {
    const d = dados.detail;
    throw new Error(typeof d === "string" ? d : (d && d.erro) || "falha");
  }
  return dados;
}

const JSON_ = (corpo) => ({
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(corpo),
});

/* Toda edição passa por aqui: erro vira mensagem na tela em vez de promessa
 * rejeitada no console, e nada roda enquanto o PDF está sendo gerado. */
async function executar(acao) {
  if (estado.ocupado) return;
  try {
    await acao();
  } catch (e) {
    mostrarAvisoTermo(e.message, true);
    if (doc) redesenhar();
  }
}

/* Depois de qualquer edição: o PDF e o texto gerados antes deixaram de valer
 * (o servidor já os apagou), e a pré-verificação precisa rodar de novo. */
function aposEdicao() {
  limparResultado();
  estado.sucesso = false;
  redesenhar();
  agendarPreverificacao();
}

async function removerSpan(spanId) {
  doc = await enviar(`/span/${spanId}`, { method: "DELETE" });
  aposEdicao();
}

async function removerVarios(ids) {
  for (const id of ids) doc = await enviar(`/span/${id}`, { method: "DELETE" });
  aposEdicao();
}

async function alternar(spanId, ativo, redesenhaDepois = true) {
  marcarRevisado(spanId);
  doc = await enviar("/span", { method: "PATCH", ...JSON_({ span_id: spanId, ativo }) });
  if (redesenhaDepois) aposEdicao();
}

async function alternarIguais(spanId, ativo) {
  doc = await enviar("/span/iguais", { method: "PATCH", ...JSON_({ span_id: spanId, ativo }) });
  aposEdicao();
}

async function mudarEntidade(spanId, entidade) {
  doc = await enviar("/span/entidade", { method: "PATCH", ...JSON_({ span_id: spanId, entidade }) });
  estado.expandidas.add(entidade);
  aposEdicao();
}

/* O modo do documento é lido do perfil, nunca guardado aqui.
 *
 * Estado paralelo no front-end é como a tela passa a dizer uma coisa e o PDF
 * a fazer outra — e a regra do projeto é que nada que o navegador guarda
 * influencia o arquivo. O servidor é a verdade; isto só a lê. */
function modoAtual() {
  return doc && doc.perfil && doc.perfil.padrao === "pseudonimo" ? "pseudonimo" : "tarja";
}

async function trocarModo(modo) {
  // Toda entidade que já sai do documento passa a sair pelo novo operador; o
  // que estava em `manter` continua em `manter`. Trocar o modo não é redecidir
  // o que é sensível — é decidir o que fica no lugar.
  const regras = {};
  for (const [entidade, op] of Object.entries(doc.perfil.regras || {})) {
    regras[entidade] = op === "manter" ? "manter" : modo;
  }
  doc = await enviar("/perfil", {
    method: "PUT",
    ...JSON_({ nome: "personalizado", padrao: modo, regras }),
  });
  aposEdicao();
}

async function alternarManuais(ligar) {
  doc = await enviar("/manuais", { method: "PATCH", ...JSON_({ ativo: ligar }) });
  aposEdicao();
}

/* A caixa da classe. Rota própria, e não `PUT /perfil`: desmarcar uma classe
 * que já estava em `manter` não muda regra nenhuma, e por isso não zerava os
 * trechos que o revisor tinha ligado um a um. A decisão do que zerar é do
 * servidor (`Sessao.alternar_entidade`). */
async function alternarEntidade(entidade, ligar) {
  doc = await enviar("/entidade", { method: "PATCH", ...JSON_({ entidade, ligar }) });
  aposEdicao();
}

for (const radio of document.querySelectorAll('input[name="modo"]')) {
  radio.addEventListener("change", () => {
    if (radio.checked) executar(() => trocarModo(radio.value));
  });
}

/* Mantém a tela dizendo a verdade sobre o que vai acontecer.
 *
 * Os textos mudam com o modo porque descrevem promessas diferentes: "tarja"
 * é falso quando o trecho vira código, e "10 vetores" é falso quando o
 * verificador roda o décimo primeiro, o de presença do código. */
function sincronizarModo() {
  const modo = modoAtual();
  const token = modo === "pseudonimo";

  for (const radio of document.querySelectorAll('input[name="modo"]')) {
    radio.checked = radio.value === modo;
  }
  $("ajuda-aprovar").textContent = token
    ? "O PDF só é gerado agora. Ele passa por verificação em 11 vetores — os " +
      "10 de sempre, mais a conferência de que todo código foi mesmo escrito."
    : "O PDF só é gerado agora. Ele passa por verificação em 10 vetores antes " +
      "de ser liberado.";

  /* Valor curto não comporta código — medido em 2026-09-16: `[CEP-2C81]` ocupa
   * 48,0pt e um CEP deixa 43,0pt. Esses trechos saem em tarja em vez de
   * reprovar o documento, e o usuário precisa saber disso ANTES de aprovar. A
   * contagem vem do servidor (`sem_token`), que mede com a régua do redator. */
  const semToken = {};
  for (const s of doc.spans || []) {
    if (s.sem_token) semToken[s.entity] = (semToken[s.entity] || 0) + 1;
  }
  const total = Object.values(semToken).reduce((a, b) => a + b, 0);
  const aviso = $("aviso-curtas");
  if (token && total) {
    const lista = Object.entries(semToken)
      .map(([e, n]) => `${categoria(e).nome} (${n})`)
      .join(", ");
    aviso.textContent =
      `${total} trecho(s) não têm espaço para o código e vão em tarja preta: ` +
      `${lista}. O valor sai do documento do mesmo jeito; o texto para a IA ` +
      `usa código em todos.`;
    aviso.classList.remove("hidden");
  } else {
    aviso.classList.add("hidden");
  }

  $("sugestao-codigo").classList.toggle("hidden", token || !$("saida-ia").checked);
}

$("btn-como-funciona").addEventListener("click", () => {
  const aberto = $("como-funciona").classList.toggle("hidden") === false;
  $("btn-como-funciona").setAttribute("aria-expanded", String(aberto));
});

$("btn-usar-codigo").addEventListener("click", () => executar(() => trocarModo("pseudonimo")));

// ------------------------------------------------------ busca e termo
let temporizadorBusca = 0;
let ultimaContagem = null;

$("termo").addEventListener("input", () => {
  clearTimeout(temporizadorBusca);
  temporizadorBusca = setTimeout(atualizarBusca, 200);
});
$("termo").addEventListener("keydown", (e) => {
  if (e.key === "Enter") {
    e.preventDefault();
    const q = $("termo").value.trim();
    if (q.length >= 2) executar(() => adicionarTermo(q));
  }
  if (e.key === "Escape") {
    $("termo").value = "";
    $("resultados-busca").classList.add("hidden");
  }
});

/* Busca entre as detecções e, ao mesmo tempo, conta no servidor quantas vezes
 * o termo aparece pelas duas réguas — a do botão e a da verificação. Quando
 * elas discordam, a tela diz **antes** do clique. Era aqui que "1 ocorrência
 * tarjada" virava 2 sobreviventes na geração. */
async function atualizarBusca() {
  const q = $("termo").value.trim();
  const caixa = $("resultados-busca");
  if (q.length < 2 || !doc) {
    caixa.classList.add("hidden");
    return;
  }
  const alvo = semAcento(q);
  const achados = [...gruposPorValor(doc.spans)]
    .filter(([valor]) => semAcento(valor).includes(alvo))
    .slice(0, 6);

  let contagem = null;
  try {
    contagem = await enviar(`/contar?termo=${encodeURIComponent(q)}`, { method: "GET" });
  } catch {
    contagem = null;
  }
  if ($("termo").value.trim() !== q) return; // o usuário continuou digitando
  ultimaContagem = { termo: q, ...contagem };

  caixa.innerHTML = "";
  for (const [valor, grupo] of achados) {
    const b = document.createElement("button");
    const v = document.createElement("span");
    v.className = "mono";
    v.textContent = valor;
    const det = document.createElement("span");
    det.className = "detalhe";
    det.textContent = `${categoria(grupo[0].entity).singular} · ${grupo.length}×`;
    b.append(v, det);
    b.addEventListener("click", () => {
      const s = grupo.find(visivelNoDocumento) || grupo[0];
      estado.expandidas.add(s.entity);
      montarCategorias();
      if (visivelNoDocumento(s)) focar(s.id);
    });
    caixa.appendChild(b);
  }

  if (contagem) {
    const add = document.createElement("button");
    add.className = "adicionar";
    const det = document.createElement("span");
    det.className = "detalhe";
    if (contagem.novas > 0) {
      add.append(`+ Anonimizar “${q}” em todo o documento`);
      det.textContent = `${contagem.novas} ${contagem.novas === 1 ? "ocorrência" : "ocorrências"}`;
      add.addEventListener("click", () => executar(() => adicionarTermo(q)));
    } else {
      add.disabled = true;
      add.append(contagem.ja_cobertas ? `“${q}” já está anonimizado` : `“${q}” não aparece no texto`);
      det.textContent = contagem.ja_cobertas ? `${contagem.ja_cobertas}×` : "confira a grafia";
    }
    add.appendChild(det);
    caixa.appendChild(add);

    const sobra = contagem.no_texto - contagem.novas - contagem.ja_cobertas;
    if (sobra > 0) {
      const nota = document.createElement("div");
      nota.className = "nota-contagem";
      nota.textContent =
        `A verificação encontra ${contagem.no_texto} ocorrências deste termo no ` +
        `texto — inclusive em outras formas, como só os dígitos. ${sobra} não ` +
        `${sobra === 1 ? "será coberta" : "serão cobertas"} por esta busca e vão ` +
        `aparecer como pendência para você resolver.`;
      caixa.appendChild(nota);
    }
  }
  caixa.classList.toggle("hidden", caixa.children.length === 0);
}

function mostrarAvisoTermo(texto, alerta = false) {
  const aviso = $("aviso-termo");
  aviso.textContent = texto;
  aviso.classList.toggle("alerta", alerta);
  aviso.classList.remove("hidden");
}

async function adicionarTermo(valor) {
  const termo = (valor !== undefined ? valor : $("termo").value).trim();
  if (termo.length < 2) return;

  const contagem = ultimaContagem && ultimaContagem.termo === termo ? ultimaContagem : null;
  doc = await enviar("/termo", { method: "POST", ...JSON_({ termo }) });
  const n = doc.adicionados;
  estado.expandidas.add("MANUAL");
  $("termo").value = "";
  $("resultados-busca").classList.add("hidden");

  // Nunca "1 ocorrência anonimizada" quando a verificação vai achar 2.
  const sobra = contagem ? contagem.no_texto - n - contagem.ja_cobertas : 0;
  if (n === 0) {
    mostrarAvisoTermo("Nenhuma ocorrência nova encontrada — verifique a grafia exata.", true);
  } else if (sobra > 0) {
    mostrarAvisoTermo(
      `${n} ${n === 1 ? "ocorrência marcada" : "ocorrências marcadas"}, mas o texto ` +
        `tem mais ${sobra} em outra forma. Elas aparecem como pendência no topo.`,
      true
    );
  } else {
    mostrarAvisoTermo(`${n} ${n === 1 ? "ocorrência marcada" : "ocorrências marcadas"}. Conferindo o arquivo…`);
  }
  aposEdicao();
}

/* ------------------------------------------------ seleção no documento ---
 *
 * `getSelection().toString()` NÃO serve aqui: cada palavra é um <span>
 * posicionado em absoluto, sem nó de espaço entre eles, e o navegador
 * concatena tudo grudado — "OFÍCIONº359/2026" — que não existe em lugar
 * nenhum do documento.
 *
 * Converte a seleção num intervalo de caracteres do documento. Cada <span> é
 * uma palavra e carrega, em `data-i`, o offset dela no texto completo. O
 * navegador informa em que caractere *dentro* do nó de texto a seleção
 * começou e terminou. A soma dos dois dá o offset exato — inclusive quando o
 * usuário seleciona no meio de uma palavra.
 *
 * Devolve também o texto, para exibir no balão e para "em todo o documento".
 * Quem manda no que é marcado em "só este trecho" são os offsets. */
function palavrasSelecionadas() {
  const sel = window.getSelection();
  if (!sel || sel.isCollapsed || !sel.rangeCount) return null;

  const range = sel.getRangeAt(0);
  const camada =
    range.commonAncestorContainer.nodeType === 1
      ? range.commonAncestorContainer.closest(".camada-texto")
      : range.commonAncestorContainer.parentElement?.closest(".camada-texto");
  if (!camada) return null; // seleção fora do documento

  const dentro = [...camada.children].filter((s) => range.intersectsNode(s));
  if (!dentro.length) return null;

  const primeiro = dentro[0];
  const ultimo = dentro[dentro.length - 1];
  const spanDe = (no) => (no.nodeType === 1 ? no : no.parentElement);

  let inicio = Number(primeiro.dataset.i);
  let fim = Number(ultimo.dataset.i) + ultimo.textContent.length;
  let corteIni = 0;
  let corteFim = ultimo.textContent.length;

  // A ponta só desloca quando ela cai *dentro* de uma palavra.
  const spanIni = spanDe(range.startContainer);
  if (spanIni === primeiro && range.startContainer.nodeType === 3) {
    corteIni = range.startOffset;
    inicio = Number(primeiro.dataset.i) + corteIni;
  }
  const spanFim = spanDe(range.endContainer);
  if (spanFim === ultimo && range.endContainer.nodeType === 3) {
    corteFim = range.endOffset;
    fim = Number(ultimo.dataset.i) + corteFim;
  }

  if (!Number.isFinite(inicio) || !Number.isFinite(fim) || fim <= inicio) return null;

  const partes = dentro.map((s) => s.textContent);
  if (partes.length === 1) {
    partes[0] = partes[0].slice(corteIni, corteFim);
  } else {
    partes[0] = partes[0].slice(corteIni);
    partes[partes.length - 1] = partes[partes.length - 1].slice(0, corteFim);
  }
  const texto = partes.join(" ").replace(/\s+/g, " ").trim();
  if (texto.length < 1) return null;
  return { texto, range, inicio, fim };
}

const balao = $("balao");
let temporizadorBalao = 0;

function esconderBalao() {
  balao.classList.add("hidden");
  balao.dataset.texto = "";
}

document.addEventListener("selectionchange", () => {
  if (!palavrasSelecionadas()) esconderBalao();
});

/* `selectionchange` dispara a cada caractere arrastado; o balão só se
 * posiciona quando o usuário solta. */
document.addEventListener("mouseup", (e) => {
  if (e.target.closest && e.target.closest("#balao")) return;
  setTimeout(() => {
    const sel = palavrasSelecionadas();
    if (!sel || estado.ocupado) return esconderBalao();
    balao.dataset.inicio = sel.inicio;
    balao.dataset.fim = sel.fim;
    balao.dataset.texto = sel.texto;

    const curto = sel.texto.length > 40 ? sel.texto.slice(0, 40) + "…" : sel.texto;
    const rotulo = $("balao-texto");
    rotulo.innerHTML = "";
    const forte = document.createElement("strong");
    forte.textContent = `“${curto}”`;
    rotulo.append(forte);
    $("balao-todas").textContent = "Anonimizar em todo o documento";
    $("balao-todas").disabled = sel.texto.length < 2;

    posicionarFlutuante(balao, sel.range.getBoundingClientRect());

    // Quantas vezes, pela régua do botão; chega um instante depois.
    clearTimeout(temporizadorBalao);
    if (sel.texto.length >= 2) {
      temporizadorBalao = setTimeout(async () => {
        try {
          const c = await enviar(`/contar?termo=${encodeURIComponent(sel.texto)}`, { method: "GET" });
          if (balao.dataset.texto !== sel.texto) return;
          ultimaContagem = { termo: sel.texto, ...c };
          $("balao-todas").textContent =
            c.novas > 0
              ? `Anonimizar em todo o documento (${c.novas} ${c.novas === 1 ? "ocorrência" : "ocorrências"})`
              : "Já anonimizado em todo o documento";
          $("balao-todas").disabled = c.novas === 0;
        } catch {}
      }, 120);
    }
  }, 0);
});

for (const id of ["balao-todas", "balao-tarjar"]) {
  // Clicar no balão não pode desfazer a seleção antes do clique.
  $(id).addEventListener("mousedown", (e) => e.preventDefault());
}

$("balao-todas").addEventListener("click", () => {
  const texto = balao.dataset.texto || "";
  esconderBalao();
  window.getSelection()?.removeAllRanges();
  if (texto.length >= 2) executar(() => adicionarTermo(texto));
});

$("balao-tarjar").addEventListener("click", async () => {
  const inicio = Number(balao.dataset.inicio);
  const fim = Number(balao.dataset.fim);
  const textoSel = balao.dataset.texto || "";
  esconderBalao();
  window.getSelection()?.removeAllRanges();
  if (!Number.isFinite(inicio) || !Number.isFinite(fim)) return;

  await executar(async () => {
    // Intervalo, não termo: marca só o que foi selecionado. O texto vai junto
    // para o servidor conferir que os offsets apontam para o mesmo trecho que
    // apareceu na tela (`Sessao._conferir_intervalo`).
    doc = await enviar("/intervalo", { method: "POST", ...JSON_({ inicio, fim, texto: textoSel }) });
    estado.expandidas.add("MANUAL");
    mostrarAvisoTermo("Trecho marcado. Conferindo o arquivo…");
    aposEdicao();
  });
});

/* -------------------------------------------------- pré-verificação ---
 *
 * A verificação da aprovação, rodada durante a revisão (`POST
 * /preverificar`). O servidor redige e verifica de verdade num arquivo que
 * apaga em seguida; aqui só se decide **quando** pedir e se a resposta ainda
 * vale. Uma resposta que chega depois de outra edição fala de uma proposta que
 * já não existe — `versao` diferente, descartada. */
let temporizadorPre = 0;
let preEmVoo = false;
let preDeNovo = false;

function agendarPreverificacao(espera = 500) {
  if (!doc) return;
  clearTimeout(temporizadorPre);
  if (!estado.previa || estado.previa.versao !== doc.versao) {
    estado.verificando = true;
    atualizarVerificacao();
  }
  temporizadorPre = setTimeout(rodarPreverificacao, espera);
}

async function rodarPreverificacao() {
  if (!doc) return;
  if (preEmVoo) {
    preDeNovo = true;
    return;
  }
  preEmVoo = true;
  const id = doc.doc_id;
  try {
    const r = await fetch(`/api/doc/${id}/preverificar`, { method: "POST" });
    if (!doc || doc.doc_id !== id) return;
    if (r.ok) {
      const dados = await r.json();
      if (dados.versao === doc.versao) {
        estado.previa = dados;
      } else {
        preDeNovo = true;
      }
    } else if (r.status !== 404) {
      estado.previa = { versao: doc.versao, erro: `a verificação falhou (${r.status})` };
    }
  } catch {
    if (doc) estado.previa = { versao: doc.versao, erro: "o servidor não respondeu" };
  } finally {
    preEmVoo = false;
    if (preDeNovo) {
      preDeNovo = false;
      rodarPreverificacao();
    } else {
      estado.verificando = false;
      if (doc) {
        atualizarVerificacao();
        atualizarMiniaturas();
      }
    }
  }
}

function previaAtual() {
  return estado.previa && doc && estado.previa.versao === doc.versao ? estado.previa : null;
}

function pendencias() {
  const p = previaAtual();
  return p && !p.erro ? p.ocorrencias || [] : [];
}

function pendenciasLegiveis() {
  return pendencias().filter((o) => o.visivel_no_texto);
}

function algumAtivo() {
  return doc.spans.some((s) => s.sera_tarjado);
}

function atualizarVerificacao() {
  if (!doc) return;
  atualizarSelo();
  montarPendencias();
  montarEtapas();
  atualizarBotaoPrincipal();
  montarChecklist();
}

function atualizarSelo() {
  const selo = $("selo-verificacao");
  const p = previaAtual();
  const pend = pendencias();
  const legiveis = pend.filter((o) => o.visivel_no_texto).length;
  let classe = "selo-neutro";
  let icon = "";
  let texto = "";

  if (!algumAtivo()) {
    texto = "Nada marcado para anonimizar ainda";
  } else if (!p || estado.verificando) {
    icon = '<span class="girando"></span>';
    texto = "Conferindo o arquivo…";
  } else if (p.erro) {
    classe = "selo-erro";
    icon = icone("alerta");
    texto = `A verificação não pôde rodar: ${p.erro}`;
  } else if (p.ok) {
    classe = "selo-ok";
    icon = icone("check");
    // "Nenhum dado marcado", e não "nenhum dado": a verificação confere os
    // valores que estão marcados. Ela não prova que não há outro dado pessoal
    // que ninguém marcou.
    texto = "Nenhum dado marcado sobrou no arquivo";
  } else if (legiveis) {
    classe = "selo-alerta";
    icon = icone("alerta");
    texto = `${legiveis} ${legiveis === 1 ? "trecho ainda legível" : "trechos ainda legíveis"}`;
  } else {
    classe = "selo-erro";
    icon = icone("alerta");
    texto = `${pend.length} ${pend.length === 1 ? "valor sobrevive" : "valores sobrevivem"} na estrutura do PDF`;
  }

  selo.className = `selo ${classe}`;
  $("selo-icone").innerHTML = icon;
  $("selo-texto").textContent = texto;
  const clicavel = pend.length > 0;
  selo.disabled = !clicavel;
  if (!clicavel) {
    $("lista-pendencias").classList.add("hidden");
    selo.setAttribute("aria-expanded", "false");
  }
}

$("selo-verificacao").addEventListener("click", () => alternarPendencias());

function alternarPendencias(abrir) {
  const lista = $("lista-pendencias");
  const aberta = abrir === undefined ? lista.classList.contains("hidden") : abrir;
  lista.classList.toggle("hidden", !aberta || !pendencias().length);
  $("selo-verificacao").setAttribute("aria-expanded", String(aberta));
}

function montarPendencias() {
  const lista = $("lista-pendencias");
  lista.innerHTML = "";
  for (const o of pendencias()) lista.appendChild(cartaoOcorrencia(o));
}

/* Um valor que sobreviveu: o quê, onde, e — quando o conserto está ao alcance
 * do usuário — o botão que o faz. */
function cartaoOcorrencia(o) {
  const card = document.createElement("div");
  card.className = "ocorrencia" + (o.visivel_no_texto ? "" : " estrutural");

  const quem = document.createElement("div");
  quem.className = "quem";
  quem.textContent = o.valor;

  const onde = document.createElement("div");
  onde.className = "onde";
  const paginas = o.paginas || [];
  onde.textContent = o.visivel_no_texto
    ? `${o.ocorrencias_no_texto} ${o.ocorrencias_no_texto === 1 ? "ocorrência legível" : "ocorrências legíveis"} no texto` +
      (paginas.length ? ` — página${paginas.length > 1 ? "s" : ""} ${paginas.join(", ")}` : "")
    : `só na estrutura do PDF${o.objeto ? " — " + o.objeto : ""} (${(o.vetores || []).join(", ")})`;
  card.append(quem, onde);

  if (o.visivel_no_texto) {
    const acoes = document.createElement("div");
    acoes.className = "acoes";
    for (const n of paginas) {
      const b = document.createElement("button");
      b.className = "secundario pequeno";
      b.textContent = `Ir para a página ${n}`;
      b.addEventListener("click", () => irParaPagina(n));
      acoes.appendChild(b);
    }
    const b = document.createElement("button");
    b.className = "primario pequeno";
    b.textContent = "Anonimizar todas";
    b.addEventListener("click", () => executar(() => adicionarTermo(o.valor)));
    acoes.appendChild(b);
    card.appendChild(acoes);
  }
  return card;
}

// ---------------------------------------------------------------- etapas
function statusDaEtapa(id) {
  const p = previaAtual();
  if (id === "revisar") return estado.aba === "exportar" || estado.sucesso ? "feito" : "atual";
  if (id === "verificar") {
    if (!algumAtivo()) return "futuro";
    if (!p || estado.verificando) return "atual";
    return p.ok ? "feito" : "atencao";
  }
  if (id === "exportar") {
    if (estado.sucesso) return "feito";
    return estado.aba === "exportar" ? "atual" : "futuro";
  }
  return "futuro";
}

function montarEtapas() {
  const ol = $("etapas");
  ol.innerHTML = "";
  ETAPAS.forEach((etapa, i) => {
    const li = document.createElement("li");
    const b = document.createElement("button");
    b.className = "etapa";
    const st = statusDaEtapa(etapa.id);
    b.dataset.status = st;
    if (st === "atual") b.setAttribute("aria-current", "step");
    const numero = document.createElement("span");
    numero.className = "numero";
    numero.textContent = st === "feito" ? "✓" : st === "atencao" ? "!" : String(i + 1);
    const rot = document.createElement("span");
    rot.className = "rotulo-etapa";
    rot.textContent = etapa.rotulo;
    b.append(numero, rot);
    b.setAttribute("aria-label", `${i + 1}. ${etapa.rotulo}`);
    b.addEventListener("click", () => irParaEtapa(etapa.id));
    li.appendChild(b);
    ol.appendChild(li);
  });
}

function irParaEtapa(id) {
  if (id === "revisar") selecionarAba("deteccoes");
  if (id === "verificar") {
    selecionarAba("deteccoes");
    alternarPendencias(true);
  }
  if (id === "exportar") selecionarAba("exportar");
  abrirInspetorEstreito();
}

// ------------------------------------------------------ botão principal
function atualizarBotaoPrincipal() {
  const b = $("btn-principal");
  const n = pendencias().length;
  b.classList.remove("pendente");
  b.disabled = !algumAtivo() || estado.ocupado;
  if (estado.ocupado) {
    b.innerHTML = `<span class="girando"></span> ${escapar(textoGerando())}`;
    return;
  }
  if (n > 0) {
    b.classList.add("pendente");
    b.textContent = `Revisar ${n} ${n === 1 ? "pendência" : "pendências"}`;
  } else if (estado.aba === "exportar") {
    b.textContent = "Gerar e baixar";
    b.disabled = b.disabled || !saidasEscolhidas().length;
  } else {
    b.textContent = "Aprovar e gerar PDF";
  }
}

$("btn-principal").addEventListener("click", () => {
  if (pendencias().length) {
    selecionarAba("deteccoes");
    alternarPendencias(true);
    abrirInspetorEstreito();
    const primeira = pendenciasLegiveis()[0];
    if (primeira && primeira.paginas && primeira.paginas.length) irParaPagina(primeira.paginas[0]);
    return;
  }
  if (estado.aba === "exportar") return gerar();
  selecionarAba("exportar");
  abrirInspetorEstreito();
});

// ------------------------------------------------------------------ abas
const ABAS = ["deteccoes", "ajustes", "exportar"];

function selecionarAba(aba) {
  estado.aba = aba;
  for (const a of ABAS) {
    const tab = $(`aba-${a}`);
    const ativa = a === aba;
    tab.setAttribute("aria-selected", String(ativa));
    tab.tabIndex = ativa ? 0 : -1;
    $(`painel-${a}`).hidden = !ativa;
  }
  if (doc) {
    montarEtapas();
    atualizarBotaoPrincipal();
  }
}

for (const a of ABAS) {
  $(`aba-${a}`).addEventListener("click", () => selecionarAba(a));
}

// Setas entre as abas, como pede o padrão de tablist.
document.querySelector('[role="tablist"]').addEventListener("keydown", (e) => {
  if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
  const i = ABAS.indexOf(estado.aba);
  const j = (i + (e.key === "ArrowRight" ? 1 : ABAS.length - 1)) % ABAS.length;
  selecionarAba(ABAS[j]);
  $(`aba-${ABAS[j]}`).focus();
  e.preventDefault();
});

// -------------------------------------------------------------- exportar
function montarChecklist() {
  const ul = $("checklist");
  ul.innerHTML = "";
  const rel = doc.relatorio;
  const p = previaAtual();
  // Depois da geração, o que vale é o relatório do arquivo gerado; antes,
  // a pré-verificação da versão atual.
  const fonte = rel
    ? { vetores: rel.vetores, vazamentos: rel.vazamentos, ok: rel.verificacao_ok }
    : p && !p.erro
      ? { vetores: p.vetores || [], vazamentos: p.vazamentos || [], ok: p.ok }
      : null;

  const item = (estadoItem, texto, detalhe = "") => {
    const li = document.createElement("li");
    const m = document.createElement("span");
    m.className = `marca-estado ${estadoItem}`;
    m.textContent = { ok: "✓", falha: "✗", pendente: "!", espera: "…" }[estadoItem];
    m.setAttribute("aria-label", { ok: "aprovado", falha: "reprovado", pendente: "pendente", espera: "aguardando" }[estadoItem]);
    const t = document.createElement("span");
    t.textContent = texto;
    li.append(m, t);
    if (detalhe) {
      const d = document.createElement("span");
      d.className = "detalhe";
      d.textContent = detalhe;
      li.appendChild(d);
    }
    ul.appendChild(li);
  };

  if (!algumAtivo()) {
    item("espera", "Marque ao menos um dado para anonimizar");
  } else if (!fonte) {
    item("espera", p && p.erro ? `Verificação indisponível: ${p.erro}` : "Conferindo o arquivo…");
  } else {
    const vaz = new Set(fonte.vazamentos);
    for (const v of fonte.vetores) {
      item(vaz.has(v) ? "falha" : "ok", NOMES_VETORES[v] || v);
    }
  }

  $("ajuda-verificacao").textContent = rel
    ? "Resultado da verificação do arquivo gerado."
    : "Conferência da versão atual, refeita a cada alteração. A verificação " +
      "completa roda de novo ao gerar o arquivo.";
}

/* O que muda além dos dados — só o que se aplica a *este* arquivo, na hora de
 * exportar. A lista fixa num acordeão no rodapé não era lida. */
function montarAvisos() {
  const ul = $("lista-avisos");
  ul.innerHTML = "";
  const c = doc.caracteristicas || {};
  const item = (texto, destaque = false, ic = "info") => {
    const li = document.createElement("li");
    if (destaque) li.className = "destaque";
    li.innerHTML = icone(ic);
    const t = document.createElement("span");
    t.innerHTML = texto;
    li.appendChild(t);
    ul.appendChild(li);
  };
  if (c.assinatura) {
    item(
      "<strong>A assinatura digital será invalidada.</strong> Remover texto muda " +
        "os bytes assinados; não há contorno. Não testado nesta fase.",
      true,
      "alerta"
    );
  }
  if (c.links) {
    item(`${c.links} ${c.links === 1 ? "link será removido" : "links serão removidos"}, inclusive os inofensivos.`);
  }
  if (c.marcadores) {
    item(`O sumário (${c.marcadores} ${c.marcadores === 1 ? "marcador" : "marcadores"}) será apagado por inteiro.`);
  }
  if (c.anexos) {
    item(`${c.anexos} ${c.anexos === 1 ? "arquivo anexado será removido" : "arquivos anexados serão removidos"}.`);
  }
  item("Metadados são zerados: autor, título, data de criação, produtor.");
  item("Layout, paginação e fontes ficam intactos — não há refluxo.");
}

function saidasEscolhidas() {
  const s = [];
  if ($("saida-pdf").checked) s.push("pdf");
  if ($("saida-texto").checked) s.push("texto");
  return s;
}

function atualizarSaidas() {
  const ia = $("saida-ia");
  ia.disabled = !analiseDisponivel;
  if (!analiseDisponivel) ia.checked = false;
  $("selo-ia").classList.toggle("hidden", analiseDisponivel);
  $("selo-ia").textContent = "Indisponível";
  $("ajuda-ia").textContent = analiseDisponivel
    ? "Manda o texto com códigos a um modelo externo e mostra a resposta aqui. " +
      "É o único caminho em que conteúdo sai desta máquina."
    : `Indisponível agora: ${analiseMotivo}.`;
  $("bloco-analise").classList.toggle("hidden", !ia.checked);
  $("btn-gerar").disabled = !algumAtivo() || !saidasEscolhidas().length || estado.ocupado;
  $("btn-previa-texto").disabled = !algumAtivo();
  $("sugestao-codigo").classList.toggle("hidden", modoAtual() === "pseudonimo" || !ia.checked);
}

for (const id of ["saida-pdf", "saida-texto"]) {
  $(id).addEventListener("change", () => {
    atualizarSaidas();
    atualizarBotaoPrincipal();
  });
}

$("saida-ia").addEventListener("change", () => {
  atualizarSaidas();
  // Para enviar, o texto precisa existir e ser lido antes. Gerar é local.
  if ($("saida-ia").checked && !doc.pode_baixar_texto) executar(gerarTexto);
});

$("btn-previa-texto").addEventListener("click", () =>
  executar(async () => {
    if (!doc.pode_baixar_texto) await gerarTexto();
    if (doc.pode_baixar_texto) {
      $("previa-texto").open = true;
      $("texto-gerado").scrollIntoView({ block: "nearest" });
    }
  })
);

function limparResultado() {
  $("resultado").classList.add("hidden");
  $("resultado").className = "hidden";
  $("resultado").innerHTML = "";
  $("texto-falha").classList.add("hidden");
}

function textoGerando() {
  return `Verificando ${modoAtual() === "pseudonimo" ? 11 : 10} camadas…`;
}

function travar(ocupado) {
  estado.ocupado = ocupado;
  $("tela-revisao").classList.toggle("ocupado", ocupado);
  const b = $("btn-gerar");
  b.disabled = ocupado || !saidasEscolhidas().length;
  b.innerHTML = ocupado ? `<span class="girando"></span> ${escapar(textoGerando())}` : "Gerar e baixar";
  atualizarBotaoPrincipal();
}

function baixar(url) {
  const a = document.createElement("a");
  a.href = url;
  a.download = "";
  document.body.appendChild(a);
  a.click();
  a.remove();
}

/* Gerar e baixar. A verificação completa roda aqui, no servidor, do zero —
 * a pré-verificação só antecipa o resultado. */
async function gerar() {
  const saidas = saidasEscolhidas();
  if (!saidas.length || estado.ocupado || !algumAtivo()) return;
  selecionarAba("exportar");
  limparResultado();
  travar(true);
  try {
    if (saidas.includes("pdf")) {
      try {
        doc = await enviar("/aprovar", { method: "POST" });
      } catch (e) {
        mostrarFalhaGeracao(e.message);
        return;
      }
      // O resultado da aprovação é a verificação mais recente desta versão.
      const rel = doc.relatorio;
      estado.previa = {
        versao: doc.versao,
        ok: rel.verificacao_ok,
        ocorrencias: rel.ocorrencias,
        vetores: rel.vetores,
        vazamentos: rel.vazamentos,
        total_vazamentos: rel.total_vazamentos,
      };
      if (!doc.pode_baixar) {
        mostrarResultado();
        return;
      }
    }
    if (saidas.includes("texto") && !doc.pode_baixar_texto) {
      await gerarTexto();
      if (!doc.pode_baixar_texto) return;
    }
    estado.sucesso = true;
    estado.exportou = true;
    if (saidas.includes("pdf")) baixar(`/api/doc/${doc.doc_id}/download`);
    else baixar(`/api/doc/${doc.doc_id}/download/texto`);
    abrirSucesso(saidas);
  } finally {
    travar(false);
    redesenhar();
  }
}

$("btn-gerar").addEventListener("click", gerar);

function mostrarFalhaGeracao(mensagem) {
  const r = $("resultado");
  r.className = "falha";
  r.innerHTML = `<div class="cabeca">Não foi possível gerar o arquivo</div>`;
  const p = document.createElement("p");
  p.textContent = mensagem;
  r.appendChild(p);
  r.classList.remove("hidden");
}

/* Reprovado. Sem link de download — o gate não é cosmético: o arquivo foi
 * apagado no servidor. Mas "reprovou" sozinho é um beco sem saída: a mensagem
 * principal diz o que fazer, e o detalhe técnico fica recolhido. */
function mostrarResultado() {
  const rel = doc.relatorio;
  const r = $("resultado");
  r.className = "falha";
  r.innerHTML = "";

  const ocorrencias = rel.ocorrencias || [];
  const legiveis = ocorrencias.filter((o) => o.visivel_no_texto);

  const cab = document.createElement("div");
  cab.className = "cabeca";
  cab.textContent =
    legiveis.length === 1
      ? "Ainda há 1 trecho legível. Anonimize-o para liberar o arquivo."
      : legiveis.length
        ? `Ainda há ${legiveis.length} trechos legíveis. Anonimize-os para liberar o arquivo.`
        : "O arquivo não foi liberado.";
  r.appendChild(cab);

  if (legiveis.length) {
    const p = document.createElement("p");
    p.textContent =
      "Quase sempre é outra ocorrência do mesmo valor que o detector não marcou.";
    r.appendChild(p);
  }
  for (const o of ocorrencias) r.appendChild(cartaoOcorrencia(o));

  if (ocorrencias.length && !legiveis.length) {
    const p = document.createElement("p");
    p.textContent =
      "Nenhuma destas sai por extração de texto — o valor sobrevive num objeto " +
      "interno do PDF. Isso é defeito do redator, não da sua revisão; reporte o " +
      "tipo de objeto indicado.";
    r.appendChild(p);
  }

  const det = document.createElement("details");
  det.className = "detalhes-tecnicos";
  const sum = document.createElement("summary");
  sum.textContent = "Detalhes técnicos";
  const ul = document.createElement("ul");
  const li1 = document.createElement("li");
  li1.textContent = `${rel.total_vazamentos} ocorrência(s) sobreviveram ao saneamento`;
  const li2 = document.createElement("li");
  li2.textContent = `vetores afetados: ${rel.vazamentos.join(", ")}`;
  ul.append(li1, li2);
  det.append(sum, ul);
  r.appendChild(det);
  r.classList.remove("hidden");
}

// -------------------------------------------------------------- sucesso
function abrirSucesso(saidas) {
  const rel = doc.relatorio;
  const ul = $("sucesso-resumo");
  ul.innerHTML = "";
  const li = (t) => {
    const x = document.createElement("li");
    x.textContent = t;
    ul.appendChild(x);
  };
  if (rel && saidas.includes("pdf")) {
    li(`${rel.spans_redigidos} ${rel.spans_redigidos === 1 ? "dado removido" : "dados removidos"} do arquivo`);
    li(
      modoAtual() === "pseudonimo"
        ? `Formato: código no lugar (${rel.tokens_escritos} códigos escritos)`
        : "Formato: tarja preta"
    );
    const semEspaco = Object.entries(rel.tarja_por_falta_de_espaco || {});
    if (semEspaco.length) {
      li(
        `${semEspaco.reduce((a, [, n]) => a + n, 0)} em tarja porque o código não cabia: ` +
          semEspaco.map(([e, n]) => `${categoria(e).nome} (${n})`).join(", ")
      );
    }
    li(`${rel.valores_checados} valores conferidos em ${rel.vetores.length} vetores; nenhum sobreviveu`);
  }
  if (saidas.includes("texto") && doc.relatorio_texto) {
    const t = doc.relatorio_texto;
    li(`Texto: ${t.spans_substituidos} trechos substituídos por ${t.tokens_distintos} códigos`);
  }
  if (doc.caracteristicas && doc.caracteristicas.assinatura) {
    li("A assinatura digital do original não vale para este arquivo.");
  }

  const dl = $("sucesso-downloads");
  dl.innerHTML = "";
  if (doc.pode_baixar) {
    const a = document.createElement("a");
    a.href = `/api/doc/${doc.doc_id}/download`;
    a.innerHTML = `${icone("download")} PDF anonimizado`;
    dl.appendChild(a);
  }
  if (doc.pode_baixar_texto) {
    const a = document.createElement("a");
    a.href = `/api/doc/${doc.doc_id}/download/texto`;
    a.innerHTML = `${icone("download")} Texto com códigos (.txt)`;
    dl.appendChild(a);
  }
  abrirModalEl($("tela-sucesso"), $("proximo-novo"));
}

/* ------------------------------------------- análise por modelo externo ---
 *
 * O único caminho do sistema que faz conteúdo sair da máquina. As travas de
 * verdade estão no servidor (`POST /analisar`): texto verificado, re-detecção
 * com limiar mais baixo, uma chamada por documento. Esta tela não substitui
 * nenhuma delas; o que ela acrescenta é o que o servidor não consegue fazer —
 * pôr o texto na frente de quem vai enviá-lo, e dizer antes do botão o que as
 * travas **não** provam (`docs/05-politica-llm.md` §2.6).
 *
 * O estado vem do servidor, como no resto do arquivo: se o texto foi
 * invalidado por uma edição, `pode_baixar_texto` volta falso e o bloco volta
 * ao começo. Nada daqui decide se algo pode sair.
 */

/* Documentos, em 50, em que algum nome real sobreviveu no arquivo final.
 *
 * Do `make eval` de 2026-09-22, refeito em 2026-09-23 com o NER corrigido
 * (mesmos números), corpus sintético, seção "Verificação pós-redação" do
 * `eval/report.md`. É número medido, não estimativa — e envelhece: quando o
 * detector mudar, isto precisa ser remedido junto. Modelo fora desta tabela
 * recebe a frase sem número, nunca o número de outro modelo. */
const NOMES_ESCAPADOS_EM_50 = {
  "bert-lenerbr": 1,
  "bertimbau-harem": 8,
  spacy: 50,
};

let textoPrevia = "";

/* Volta o bloco ao estado "nada gerado". A mensagem de falha da geração não
 * entra aqui: ela precisa sobreviver ao redesenho que segue a própria falha,
 * e sai em `limparResultado`, que toda edição chama. */
function limparAnalise() {
  textoPrevia = "";
  $("texto-previa").textContent = "";
  $("texto-gerado").classList.add("hidden");
  $("resposta-analise").classList.add("hidden");
  $("resposta-analise").innerHTML = "";
  $("chk-consentimento").checked = false;
  $("btn-analisar").disabled = true;
}

function sincronizarAnalise() {
  if (!doc) return;
  $("envio-externo").classList.toggle("hidden", !analiseDisponivel);
  $("envio-indisponivel").classList.toggle("hidden", analiseDisponivel);
  $("envio-indisponivel").textContent =
    `Envio a modelo externo indisponível: ${analiseMotivo}. ` +
    `O texto pode ser lido e baixado mesmo assim.`;
  atualizarSaidas();

  if (!doc.pode_baixar_texto) {
    // Edição depois de gerar: o servidor apagou o texto, e o consentimento
    // dado para aquele texto não vale para o próximo.
    limparAnalise();
    return;
  }

  const rel = doc.relatorio_texto;
  $("texto-relatorio").textContent =
    `${rel.spans_substituidos} trechos substituídos por ${rel.tokens_distintos} ` +
    `códigos. Conferido: nenhum dos ${rel.valores_checados} valores ` +
    `substituídos sobreviveu, e todo código está no texto.`;
  $("link-texto").href = `/api/doc/${doc.doc_id}/download/texto`;

  const n = NOMES_ESCAPADOS_EM_50[nerAtivo];
  $("taxa-nomes").textContent =
    n === undefined
      ? "Nomes de pessoa podem escapar à detecção."
      : `Nos testes com documentos sintéticos, usando este mesmo detector ` +
        `(${nerAtivo}), algum nome escapou em ${n} de cada 50 documentos.`;

  const envios = doc.envios || [];
  const ant = $("envios-anteriores");
  ant.classList.toggle("hidden", envios.length === 0);
  ant.textContent = `Este documento já foi enviado ${envios.length} vez(es) nesta sessão.`;

  // Sessão retomada depois de um F5: o texto existe no servidor, mas a prévia
  // não está neste navegador. Sem ela a recusa da re-detecção não teria como
  // mostrar o trecho.
  if (!textoPrevia) carregarPrevia().catch(() => {});

  $("texto-gerado").classList.remove("hidden");
  $("texto-falha").classList.add("hidden");
  $("btn-analisar").disabled = !$("chk-consentimento").checked;
}

/* A prévia vem da mesma rota do download, atrás do mesmo gate: o que se lê
 * aqui é byte a byte o que será enviado, e não uma reconstrução local. */
async function carregarPrevia() {
  const r = await fetch(`/api/doc/${doc.doc_id}/download/texto`);
  if (!r.ok) throw new Error("o texto gerado não pôde ser lido");
  textoPrevia = await r.text();
  $("texto-previa").textContent = textoPrevia;
}

$("chk-consentimento").addEventListener("change", () => {
  $("btn-analisar").disabled = !$("chk-consentimento").checked;
});

async function gerarTexto() {
  limparAnalise();
  $("texto-falha").classList.add("hidden");
  try {
    doc = await enviar("/pseudonimizar", { method: "POST" });
    if (doc.pode_baixar_texto) {
      await carregarPrevia();
    } else {
      mostrarFalhaTexto(doc.relatorio_texto);
    }
  } catch (e) {
    mostrarFalhaTexto(null, e.message);
  } finally {
    redesenhar();
  }
}

function mostrarFalhaTexto(rel, mensagem) {
  const f = $("texto-falha");
  f.className = "falha";
  f.innerHTML = `<div class="cabeca">Texto reprovado na verificação — nada foi gerado</div>`;
  const p = document.createElement("p");
  if (mensagem) {
    p.textContent = mensagem;
  } else {
    // Código não é dado pessoal: pode ser nomeado. O valor, não.
    const perdidos = (rel && rel.tokens_ausentes) || [];
    p.textContent =
      `${rel ? rel.total_vazamentos : "?"} ocorrência(s) em: ` +
      `${rel ? rel.vazamentos.join(", ") : "?"}.` +
      (perdidos.length ? ` Códigos que se perderam: ${perdidos.join(", ")}.` : "");
  }
  f.appendChild(p);
}

$("btn-analisar").addEventListener("click", async () => {
  // Consentimento é por envio, não por sessão: desmarca antes de qualquer
  // outra coisa, para que um segundo clique exija decidir de novo.
  $("chk-consentimento").checked = false;
  $("btn-analisar").disabled = true;
  $("analisando").classList.remove("hidden");
  const saida = $("resposta-analise");
  saida.classList.add("hidden");
  saida.innerHTML = "";

  try {
    const r = await fetch(`/api/doc/${doc.doc_id}/analisar`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ prompt: $("pergunta").value.trim() || undefined }),
    });
    const dados = await r.json();
    if (!r.ok) {
      mostrarRecusaEnvio(dados.detail);
    } else {
      mostrarResposta(dados);
    }
    // O envio entrou na trilha do servidor; relê o estado para a contagem.
    doc = await enviar("", { method: "GET" });
  } catch (e) {
    saida.className = "falha";
    saida.innerHTML = `<div class="cabeca">Falhou</div>`;
    const p = document.createElement("p");
    p.textContent = e.message;
    saida.appendChild(p);
  } finally {
    $("analisando").classList.add("hidden");
    saida.classList.remove("hidden");
    redesenhar();
  }
});

function mostrarResposta(dados) {
  const a = dados.analise;
  const saida = $("resposta-analise");
  saida.className = "ok";
  const cab = document.createElement("div");
  cab.className = "cabeca";
  cab.textContent = `Resposta de ${a.modelo}`;
  // textContent, nunca innerHTML: é texto vindo de fora da máquina.
  const corpo = document.createElement("div");
  corpo.className = "texto-resposta";
  corpo.textContent = a.resposta;
  const meta = document.createElement("p");
  meta.className = "auxiliar";
  meta.textContent =
    `${a.caracteres_enviados} caracteres enviados, ${a.duracao_s}s. ` +
    `Os códigos na resposta são os mesmos do texto; o original está com você.`;
  saida.append(cab, corpo, meta);
}

/* A recusa da re-detecção vem com entidade e posição, nunca com o valor — o
 * servidor não copia para a resposta o dado que acabou de descobrir que não
 * devia estar ali. A tela mostra o trecho a partir da prévia, que já está
 * neste navegador, para o revisor poder corrigir.
 *
 * As posições são contadas pelo Python em code points; `slice` do JavaScript
 * conta UTF-16. Com um caractere fora do plano básico antes do achado, as duas
 * contagens divergem e o trecho mostrado seria o vizinho — o mesmo problema
 * que `Sessao._conferir_intervalo` resolve do outro lado. `Array.from` separa
 * por code point, e aí as contas batem. */
function mostrarRecusaEnvio(detalhe) {
  const saida = $("resposta-analise");
  saida.className = "falha";
  if (!detalhe || typeof detalhe === "string") {
    saida.innerHTML = `<div class="cabeca">Nada foi enviado</div>`;
    const p = document.createElement("p");
    p.textContent = detalhe || "o servidor recusou o envio";
    saida.appendChild(p);
    return;
  }

  saida.innerHTML = `
    <div class="cabeca">Nada foi enviado</div>
    <p>
      A conferência antes do envio achou no texto algo que deveria ter sido
      substituído. Quase sempre é outra ocorrência que o detector não marcou.
    </p>`;
  const pontos = Array.from(textoPrevia);
  const vistos = new Set();
  for (const a of detalhe.achados || []) {
    const trecho = pontos.slice(a.inicio, a.fim).join("");
    const chave = `${a.entidade}|${trecho}`;
    if (vistos.has(chave)) continue;
    vistos.add(chave);

    const card = document.createElement("div");
    card.className = "ocorrencia";
    const quem = document.createElement("div");
    quem.className = "quem";
    quem.textContent = trecho || `(posição ${a.inicio}–${a.fim})`;
    const onde = document.createElement("div");
    onde.className = "onde";
    onde.textContent = `detectado como ${categoria(a.entidade).singular}`;
    card.append(quem, onde);
    if (trecho.trim().length >= 2) {
      const b = document.createElement("button");
      b.className = "primario pequeno";
      b.textContent = "Substituir todas as ocorrências";
      // Mesmo caminho do termo digitado. A edição invalida o texto gerado, e
      // o usuário gera de novo antes de poder enviar.
      b.addEventListener("click", () => executar(() => adicionarTermo(trecho)));
      card.appendChild(b);
    }
    saida.appendChild(card);
  }
}

// ------------------------------------------------------------- modais
/* Mecânica compartilhada pelos modais: Esc fecha, Tab não escapa para a tela
 * inerte atrás, e o foco volta para onde estava. */
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
  focoAnterior?.focus?.();
}

function teclaNoModal(e) {
  if (!modalAberto) return;
  if (e.key === "Escape") return fecharModalEl(modalAberto);
  if (e.key !== "Tab") return;
  const foco = [...modalAberto.querySelectorAll("button, a[href]")];
  const i = foco.indexOf(document.activeElement);
  e.preventDefault();
  foco[(i + (e.shiftKey ? foco.length - 1 : 1) + foco.length) % foco.length]?.focus();
}

// Clique na sobreposição cancela; clique dentro do cartão, não.
function fecharAoClicarFora(fundo) {
  fundo.addEventListener("click", (e) => {
    if (e.target === fundo) fecharModalEl(fundo);
  });
}

/* Menu do arquivo. Descartar mora aqui, atrás de um menu e de uma
 * confirmação — não como um botão do mesmo peso que qualquer outro, ao lado
 * do nome do arquivo. */
function fecharMenuArquivo() {
  $("menu-arquivo").classList.add("hidden");
  $("btn-arquivo").setAttribute("aria-expanded", "false");
}

$("btn-arquivo").addEventListener("click", () => {
  const abrir = $("menu-arquivo").classList.contains("hidden");
  fecharPopovers();
  if (abrir) {
    $("menu-arquivo").classList.remove("hidden");
    $("btn-arquivo").setAttribute("aria-expanded", "true");
    $("menu-arquivo").querySelector("button").focus();
  }
});

/* Confirmação de descarte. Não é só estética: o diálogo do navegador não
 * permite explicar **o que** está sendo destruído, e aqui a ação apaga o
 * original, a proposta e o PDF gerado, sem volta. */
const modalFundo = $("modal-fundo");
let depoisDeDescartar = null;

function abrirModal(depois = null) {
  fecharMenuArquivo();
  depoisDeDescartar = depois;
  // `estado.exportou`, e não só `pode_baixar`: editar depois de baixar apaga
  // o arquivo no servidor, mas o que foi baixado continua com o usuário — e
  // "nada foi exportado" seria falso.
  // Depois de um F5 a tela não sabe se houve download antes (`null`), e aí
  // não afirma nada que não saiba.
  $("modal-situacao").textContent =
    estado.exportou || (doc && (doc.pode_baixar || doc.pode_baixar_texto))
      ? "Um arquivo anonimizado já foi gerado nesta revisão. O que você baixou continua com você."
      : estado.exportou === false
        ? "Nada foi exportado ainda."
        : "Se você já baixou um arquivo desta revisão, ele continua com você.";
  $("modal-alerta").textContent = "A ação é irreversível e a sessão não pode ser recuperada.";
  $("modal-confirmar").textContent = depois ? "Descartar e escolher outro" : "Descartar";
  // Foco no botão seguro: Enter sem ler não pode destruir a sessão.
  abrirModalEl(modalFundo, $("modal-cancelar"));
}
const fecharModal = () => fecharModalEl(modalFundo);

$("btn-descartar").addEventListener("click", () => abrirModal());
$("menu-trocar").addEventListener("click", () => abrirModal(() => $("arquivo").click()));
$("modal-cancelar").addEventListener("click", fecharModal);
fecharAoClicarFora(modalFundo);

$("modal-confirmar").addEventListener("click", async () => {
  const btn = $("modal-confirmar");
  const rotulo = btn.textContent;
  btn.disabled = true;
  btn.textContent = "Descartando…";
  try {
    // Espera o servidor confirmar que apagou **antes** de limpar a tela.
    const r = await fetch(`/api/doc/${doc.doc_id}`, { method: "DELETE" });
    if (!r.ok && r.status !== 404) throw new Error("o servidor recusou apagar");
    fecharModal();
    voltarAoInicio();
    if (depoisDeDescartar) depoisDeDescartar();
  } catch (e) {
    $("modal-alerta").textContent =
      `Não foi possível descartar: ${e.message}. Os arquivos continuam no servidor.`;
  } finally {
    btn.textContent = rotulo;
    btn.disabled = false;
  }
});

/* ------------------------------------------------ depois do download -----
 *
 * Aparece só quando o arquivo já foi liberado e baixado. Nesse ponto,
 * descartar a sessão não perde trabalho nenhum — o entregável está na máquina
 * do usuário —, e deixá-la viva mantém o documento original em disco sem
 * motivo. "Continuar revisando" existe porque o download pode ter sido um
 * teste: a pessoa quer conferir o arquivo antes de abrir mão da sessão.
 */
const sucessoFundo = $("tela-sucesso");
fecharAoClicarFora(sucessoFundo);

$("proximo-fechar").addEventListener("click", () => fecharModalEl(sucessoFundo));

async function encerrarSessao() {
  const id = doc?.doc_id;
  fecharModalEl(sucessoFundo);
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
  clearTimeout(temporizadorPre);
  estado.previa = null;
  estado.focado = null;
  estado.sucesso = false;
  estado.exportou = false;
  esconderBalao();
  esconderDica();
  fecharPopovers();
  window.getSelection()?.removeAllRanges();

  $("coluna-original").innerHTML = "";
  $("coluna-anonimizado").innerHTML = "";
  $("miniaturas").innerHTML = "";
  $("lista-categorias").innerHTML = "";
  $("lista-pendencias").innerHTML = "";
  $("termo").value = "";
  $("resultados-busca").classList.add("hidden");
  $("aviso-termo").classList.add("hidden");
  $("saida-ia").checked = false;
  limparResultado();
  limparAnalise();
  document.title = "Anonimizador — revisão";

  $("tela-revisao").classList.add("hidden");
  $("cabecalho-doc").classList.add("hidden");
  $("etapas").classList.add("hidden");
  $("topo-acoes").classList.add("hidden");
  $("tela-upload").classList.remove("hidden");
  $("zona").classList.remove("hidden");
  $("erro-upload").classList.add("hidden");
  $("arquivo").value = "";
  window.scrollTo(0, 0);
}

// ------------------------------------------------------------- atalhos
$("btn-atalhos").addEventListener("click", () => {
  const p = $("popover-atalhos");
  const abrir = p.classList.contains("hidden");
  fecharPopovers();
  if (abrir) {
    p.classList.remove("hidden");
    $("btn-atalhos").setAttribute("aria-expanded", "true");
  }
});

function digitando(el) {
  return el && (el.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName));
}

document.addEventListener("keydown", (e) => {
  if (modalAberto || !doc || e.ctrlKey || e.metaKey || e.altKey) return;
  if (e.key === "Escape") {
    fecharPopovers();
    esconderBalao();
    esconderDica();
    fecharInspetorEstreito();
    return;
  }
  if (digitando(e.target) || estado.ocupado) return;
  const naMarcacao = e.target.classList && e.target.classList.contains("tarja");

  switch (e.key) {
    case "j":
    case "J":
    case "ArrowDown":
      e.preventDefault();
      passo(1);
      break;
    case "k":
    case "K":
    case "ArrowUp":
      e.preventDefault();
      passo(-1);
      break;
    case " ": {
      const s = doc.spans.find((x) => x.id === estado.focado);
      if (!s || (e.target.tagName === "BUTTON" && !naMarcacao)) return;
      e.preventDefault();
      executar(() => alternar(s.id, !s.sera_tarjado));
      break;
    }
    case "Enter": {
      if (!naMarcacao) return;
      const s = doc.spans.find((x) => x.id === e.target.dataset.spanId);
      if (s) {
        e.preventDefault();
        abrirPopoverMarca(s, e.target);
      }
      break;
    }
    case "p":
    case "P":
      if (estado.vista !== "original") alternarPreviaFinal();
      break;
    case "?":
      $("btn-atalhos").click();
      break;
    case "+":
    case "=":
      mudarZoom(1);
      break;
    case "-":
      mudarZoom(-1);
      break;
    default:
  }
});

// ---------------------------------------------------------- responsivo
telaEstreita.addEventListener("change", () => {
  if (estado.vista === "comparar" && telaEstreita.matches) aplicarVista("anonimizado");
  if (!telaEstreita.matches) fecharInspetorEstreito();
});

$("btn-inspetor").addEventListener("click", () => {
  if ($("inspetor").classList.contains("aberto")) fecharInspetorEstreito();
  else abrirInspetorEstreito();
});

function abrirInspetorEstreito() {
  if (!telaEstreita.matches) return;
  $("inspetor").classList.add("aberto");
  $("btn-inspetor").setAttribute("aria-expanded", "true");
}

function fecharInspetorEstreito() {
  $("inspetor").classList.remove("aberto");
  $("btn-inspetor").setAttribute("aria-expanded", "false");
}

/* O trilho recolhe sozinho abaixo de 1280px; o botão alterna nos dois casos. */
$("btn-trilho").addEventListener("click", () => {
  const tela = $("tela-revisao");
  let aberto;
  if (telaMedia.matches) {
    aberto = tela.classList.toggle("trilho-aberto");
  } else {
    aberto = !tela.classList.toggle("trilho-recolhido");
  }
  $("btn-trilho").setAttribute("aria-expanded", String(aberto));
  $("btn-trilho").setAttribute("aria-label", aberto ? "Recolher miniaturas" : "Mostrar miniaturas");
  requestAnimationFrame(aplicarLargura);
});

// ---------------------------------------------------------------- ícones
/* Traço 1.5, grade de 24 — desenhados aqui, sem biblioteca: a interface não
 * carrega nada de fora (a máquina que processa documento não tem rede, e o
 * navegador de quem revisa não precisa de uma). */
const ICONES = {
  chevron: '<path d="m9 6 6 6-6 6"/>',
  check: '<path d="m5 12.5 4.5 4.5L19 7.5"/>',
  alerta: '<path d="M12 4 2.8 19.5h18.4L12 4Z"/><path d="M12 10v4.5"/><path d="M12 17.2v.1"/>',
  info: '<circle cx="12" cy="12" r="8.5"/><path d="M12 11v5"/><path d="M12 8v.1"/>',
  lixeira: '<path d="M4.5 7h15"/><path d="M9.5 7V4.5h5V7"/><path d="M6.5 7l1 12.5h9l1-12.5"/>',
  download: '<path d="M12 4v11"/><path d="m7.5 10.5 4.5 4.5 4.5-4.5"/><path d="M5 19.5h14"/>',
};

function icone(nome) {
  return `<svg class="ic" viewBox="0 0 24 24" aria-hidden="true">${ICONES[nome] || ""}</svg>`;
}

function escapar(s) {
  const d = document.createElement("div");
  d.textContent = String(s);
  return d.innerHTML;
}
