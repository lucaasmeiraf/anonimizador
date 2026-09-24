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
    for (const [i, r] of s.rects.entries()) {
      const pagina = doc.paginas[r.pagina];
      const camada = camadas[r.pagina];
      if (!pagina || !camada) continue;

      const caixa = document.createElement("span");
      caixa.className = "tarja";
      if (!s.sera_tarjado) caixa.classList.add("desligada");
      if (s.origem === "usuario") caixa.classList.add("manual");
      /* Código no lugar: desenha o que o redator vai fazer — caixa branca, e
       * o código só na primeira caixa do trecho (um valor que quebra a linha
       * tem duas, e repetir o código faria enxergar dois atores). O corpo sai
       * da altura da caixa pelo mesmo fator do redator (`FATOR_CORPO`), em
       * `cqw` da camada, para acompanhar o zoom sem recalcular.
       *
       * `s.token` vem do servidor e já considera a largura: onde o código não
       * cabe ele é nulo e a caixa continua tarja, como no PDF. */
      if (s.sera_tarjado && s.token) {
        caixa.classList.add("codigo");
        if (i === 0) {
          caixa.textContent = s.token;
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
      const porque =
        s.nota === "checksum_invalido"
          ? " · forma válida, dígito verificador inválido — confira"
          : "";
      const destino = !s.sera_tarjado
        ? "NÃO será alterado"
        : s.token
          ? `vira ${s.token}`
          : s.sem_token
            ? "será tarjado — o código não cabe neste espaço"
            : "será tarjado";
      caixa.title = `${s.entity} · ${destino}` + porque;
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
        s.origem === "usuario"
          ? removerSpan(s.id)
          : // Alterna o efeito **visível**, não o campo interno. Alternar
            // `ativo` deixava o clique sem efeito sempre que a política da
            // classe fosse `manter`, porque as duas condições eram um E.
            alternar(s.id, !s.sera_tarjado)
      );
      camada.appendChild(caixa);
    }
  }
  montarInventario();
  montarListaManuais();
  atualizarBotaoAprovar();
  sincronizarModo();
  sincronizarAnalise();
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
    // Sem ocorrência não há o que ligar.
    //
    // `MANUAL` era desabilitada aqui, e esse era o defeito D-02: o usuário
    // clicava para desligar tudo o que tinha apontado e nada acontecia. Ela
    // funciona agora, por um caminho próprio — `MANUAL` não é entidade de
    // política, então mexer no perfil dela seria recusado pelo servidor, com
    // razão. O lote mexe no estado dos trechos, como o clique individual.
    chk.disabled = vazia;
    chk.title = vazia
      ? "nenhuma ocorrência encontrada neste documento"
      : entidade === "MANUAL"
        ? "ligar/desligar de uma vez os trechos que você apontou"
        : "ligar/desligar a classe inteira";
    chk.addEventListener("change", () =>
      entidade === "MANUAL"
        ? alternarManuais(chk.checked)
        : alternarEntidade(entidade, chk.checked)
    );

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

/* O modo do documento é lido do perfil, nunca guardado aqui.
 *
 * Estado paralelo no front-end é como a tela passa a dizer uma coisa e o PDF
 * a fazer outra — e a regra do projeto é que nada que o navegador guarda
 * influencia o arquivo. O servidor é a verdade; isto só a lê. */
function modoAtual() {
  return doc && doc.perfil && doc.perfil.padrao === "pseudonimo"
    ? "pseudonimo"
    : "tarja";
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
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ nome: "personalizado", padrao: modo, regras }),
  });
  limparResultado();
  redesenhar();
}

async function alternarManuais(ligar) {
  doc = await enviar("/manuais", {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ativo: ligar }),
  });
  limparResultado();
  redesenhar();
}

/* A caixa da classe. Rota própria, e não `PUT /perfil`: desmarcar uma classe
 * que já estava em `manter` não muda regra nenhuma, e por isso não zerava os
 * trechos que o revisor tinha ligado um a um — a caixa ficava marcada e nada
 * acontecia. A decisão do que zerar é do servidor (`Sessao.alternar_entidade`). */
async function alternarEntidade(entidade, ligar) {
  doc = await enviar("/entidade", {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ entidade, ligar }),
  });
  limparResultado();
  redesenhar();
}

for (const radio of document.querySelectorAll('input[name="modo"]')) {
  radio.addEventListener("change", async () => {
    if (radio.checked) await trocarModo(radio.value);
  });
}

/* Mantém a tela dizendo a verdade sobre o que vai acontecer.
 *
 * Os textos mudam com o modo porque descrevem promessas diferentes: "será
 * tarjado" é falso quando o trecho vira código, e "10 vetores" é falso quando
 * o verificador roda o décimo primeiro, o de presença do código. */
function sincronizarModo() {
  const modo = modoAtual();
  const token = modo === "pseudonimo";

  for (const radio of document.querySelectorAll('input[name="modo"]')) {
    radio.checked = radio.value === modo;
  }
  // O título fica **neutro** nos dois modos: "tarjado" descrevia bem quando só
  // havia um operador e passou a descrever metade do produto. A lista é a
  // mesma lista — o que muda é o que fica no lugar, e isso o bloco de escolha
  // acima já diz.
  $("titulo-inventario").textContent = "O que será anonimizado";
  $("btn-termo").textContent = token ? "Substituir" : "Tarjar";
  $("ajuda-aprovar").textContent = token
    ? "O PDF só é gerado agora. Ele passa por verificação em 11 vetores — os " +
      "10 de sempre, mais a conferência de que todo código foi mesmo escrito."
    : "O PDF só é gerado agora. Ele passa por verificação em 10 vetores antes " +
      "de ser liberado.";

  /* Valor curto não comporta código — medido em 2026-09-16: `[CEP-2C81]` ocupa
   * 48,0pt e um CEP deixa 43,0pt. Desde 2026-09-23 esses trechos saem em
   * tarja em vez de reprovar o documento, e o usuário precisa saber disso
   * ANTES de aprovar: é menos "quem é quem" do que ele pediu. A contagem vem
   * do servidor (`sem_token`), que mede com a mesma régua do redator. */
  const semToken = {};
  for (const s of doc.spans || []) {
    if (s.sem_token) semToken[s.entity] = (semToken[s.entity] || 0) + 1;
  }
  const total = Object.values(semToken).reduce((a, b) => a + b, 0);
  const aviso = $("aviso-curtas");
  if (token && total) {
    const lista = Object.entries(semToken)
      .map(([e, n]) => `${e} (${n})`)
      .join(", ");
    aviso.textContent =
      `${total} trecho(s) não têm espaço para o código e vão em tarja preta: ` +
      `${lista}. O valor sai do documento do mesmo jeito; o texto para a IA ` +
      `usa código em todos.`;
    aviso.classList.remove("hidden");
  } else {
    aviso.classList.add("hidden");
  }
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
  $("texto-falha").classList.add("hidden");
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
    // Troca de código por tarja nunca é silenciosa: se aconteceu, está aqui.
    const semEspaco = Object.entries(rel.tarja_por_falta_de_espaco || {});
    const linhaSemEspaco = semEspaco.length
      ? `<li>${semEspaco.reduce((a, [, n]) => a + n, 0)} em tarja porque o ` +
        `código não cabia: ${escapar(semEspaco.map(([e, n]) => `${e} (${n})`).join(", "))}</li>`
      : "";
    r.innerHTML = `
      <div class="cabeca">Verificação aprovada</div>
      <ul>
        <li>${rel.spans_redigidos} trechos redigidos, ${rel.retangulos} retângulos</li>
        ${rel.tokens_escritos ? `<li>${rel.tokens_escritos} códigos escritos no lugar do valor</li>` : ""}
        ${linhaSemEspaco}
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
      const paginas = o.paginas || [];
      onde.textContent = o.visivel_no_texto
        ? `${o.ocorrencias_no_texto} ocorrência(s) legíveis no texto` +
          (paginas.length
            ? ` — página${paginas.length > 1 ? "s" : ""} ${paginas.join(", ")}`
            : "")
        : `só na estrutura do PDF${o.objeto ? " — " + o.objeto : ""} ` +
          `(${o.vetores.join(", ")})`;

      card.append(quem, onde);

      // Atalho para a página, no painel Anonimizado: é lá que o trecho
      // legível pode ser selecionado e marcado à mão, quando "tarjar todas"
      // não é o conserto certo.
      if (o.visivel_no_texto && paginas.length) {
        const ir = document.createElement("div");
        ir.className = "ir-paginas";
        for (const n of paginas) {
          const b = document.createElement("button");
          b.className = "secundario";
          b.textContent = `Ir para a página ${n}`;
          b.addEventListener("click", () => irParaPagina(n));
          ir.appendChild(b);
        }
        card.appendChild(ir);
      }

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
 * (mesmos números), corpus sintético, seção "Verificação
 * pós-redação" do `eval/report.md`. É número medido, não estimativa — e
 * envelhece: quando o detector mudar, isto precisa ser remedido junto, ou o
 * aviso passa a afirmar uma taxa que já não é a do sistema. Modelo fora desta
 * tabela recebe a frase sem número, nunca o número de outro modelo. */
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
  $("bloco-analise").classList.remove("hidden");
  $("envio-externo").classList.toggle("hidden", !analiseDisponivel);
  $("envio-indisponivel").classList.toggle("hidden", analiseDisponivel);
  $("envio-indisponivel").textContent =
    `Envio a modelo externo indisponível: ${analiseMotivo}. ` +
    `O texto pode ser lido e baixado mesmo assim.`;

  $("btn-gerar-texto").disabled = !doc.spans.some((s) => s.sera_tarjado);

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

$("btn-gerar-texto").addEventListener("click", async () => {
  const btn = $("btn-gerar-texto");
  btn.disabled = true;
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
});

function mostrarFalhaTexto(rel, mensagem) {
  const f = $("texto-falha");
  f.className = "falha";
  f.innerHTML = `<div class="cabeca">Texto reprovado na verificação — nada foi gerado</div>`;
  const p = document.createElement("p");
  p.className = "aviso";
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
  meta.className = "aviso";
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
    <p class="aviso">
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
    onde.textContent = `detectado como ${a.entidade}`;
    card.append(quem, onde);
    if (trecho.trim().length >= 2) {
      const b = document.createElement("button");
      b.textContent = "Substituir todas as ocorrências";
      // Mesmo caminho do termo digitado. A edição invalida o texto gerado, e
      // o usuário gera de novo antes de poder enviar.
      b.addEventListener("click", () => adicionarTermo(trecho));
      card.appendChild(b);
    }
    saida.appendChild(card);
  }
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
  limparAnalise();

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

/* `n` como o servidor e o rótulo contam: a partir de 1. `data-n` guarda o
 * índice a partir de 0, que é o da rota de imagem. */
function irParaPagina(n) {
  const alvo = $("rolagem-dir").querySelector(`.pagina[data-n="${n - 1}"]`);
  alvo?.scrollIntoView({ behavior: "smooth", block: "start" });
}

function escapar(s) {
  const d = document.createElement("div");
  d.textContent = String(s);
  return d.innerHTML;
}
