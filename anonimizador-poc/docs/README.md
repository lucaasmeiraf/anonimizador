# Documentação — Anonimizador

| Documento | Para quê | Quem lê |
|---|---|---|
| [`01-inventario-marco-zero.md`](01-inventario-marco-zero.md) | tudo que existe hoje: dependências, versões, licenças, modelos, estado de verificação | quem precisa saber o que estamos usando e com que risco |
| [`02-requisitos.md`](02-requisitos.md) | requisitos funcionais, não-funcionais, de segurança, normativos e operacionais, com o estado de cada um | quem valida escopo e quem monta proposta |
| [`03-configuracao.md`](03-configuracao.md) | todos os pontos de ajuste, o que fazem e o que quebra ao mexer | quem calibra a ferramenta para um cliente |
| [`04-implantacao.md`](04-implantacao.md) | passo a passo do zero ao ambiente do cliente, inclusive air-gap | quem instala e quem opera |
| [`05-politica-llm.md`](05-politica-llm.md) | onde uma LLM entra, o que faz em cada ponto e a que dados tem acesso — normativo | quem projeta o copiloto e quem responde por LGPD |
| [`06-resultados-fase-0.md`](06-resultados-fase-0.md) | leitura dos números do eval, correções aplicadas, decisão em aberto sobre o critério de recomendação e o que segue sem medição | quem decide a arquitetura da Fase 1 |
| [`explicacao-para-o-cliente.html`](explicacao-para-o-cliente.html) | o que a ferramenta faz, garante e **não** faz, em linguagem natural — sem jargão técnico | cliente final, decisor, encarregado de dados |

O escopo e os decision gates da fase atual estão em
[`../../goal-fase-0.md`](../../goal-fase-0.md).
Visão geral técnica e diagrama do pipeline em [`../README.md`](../README.md).
Apresentação da ferramenta, para quem chega ao projeto: [`../../README.md`](../../README.md).

## Duas coisas para saber antes de qualquer conversa comercial

1. **PyMuPDF é AGPL-3.0 ou licença comercial da Artifex**, e o checkpoint de
   NER jurídico não declara licença. As duas travas estão em
   [`02-requisitos.md`](02-requisitos.md), RN-04 e RN-05. Não impedem
   desenvolvimento; impedem entrega.
2. **O que existe hoje é um pipeline validado por métricas, não um produto.**
   A lista do que falta está no fim de
   [`04-implantacao.md`](04-implantacao.md).
3. **A escolha da configuração de NER foi feita: `bert-lenerbr`** (D1), pelo
   critério de *taxa de documentos sem vazamento*, não por F1 — que já apontou
   para a configuração errada duas vezes. Reconfirmada por medição em
   2026-08-31: 1 documento com vazamento contra 9 da alternativa. Ver
   `../../goal-fase-1.md`, D1.
