# Fase 0 - imagem unica para dev, teste, avaliacao e demonstracao.
# Regra da fase: NADA e instalado no host. O container e o ambiente canonico.
FROM python:3.12-slim

# CPU por padrao. Para GPU:
#   docker build --build-arg TORCH_INDEX=https://download.pytorch.org/whl/cu124 ...
ARG TORCH_INDEX=https://download.pytorch.org/whl/cpu
ARG TORCH_VERSION=2.9.1

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app/src \
    HF_HOME=/opt/models/hf \
    XDG_CACHE_HOME=/opt/models/cache

WORKDIR /app

# --- dependencias de sistema (minimas) ---
RUN apt-get update \
 && apt-get install -y --no-install-recommends make \
 && rm -rf /var/lib/apt/lists/*

# --- dependencias Python ---
COPY requirements.txt /app/requirements.txt
RUN pip install --upgrade pip \
 && pip install --index-url "${TORCH_INDEX}" "torch==${TORCH_VERSION}" \
 && pip install -r /app/requirements.txt

# --- modelos gravados na imagem (unico momento com rede) ---
# spaCy PT: tokenizacao/lematizacao (exigida pelo enriquecedor de contexto do
# Presidio) + primeira configuracao de NER.
RUN python -m spacy download pt_core_news_lg

# Checkpoints de NER PT-BR ja ajustados para token-classification.
# Ver goal-fase-0.md: neuralmind/bert-base-portuguese-cased NAO serve aqui,
# e um LM sem cabeca de NER.
RUN python - <<'PY'
from transformers import AutoTokenizer, AutoModelForTokenClassification
for mid in ("pierreguillou/ner-bert-base-cased-pt-lenerbr",
            "marquesafonso/bertimbau-large-ner-selective"):
    print("baixando", mid, flush=True)
    AutoTokenizer.from_pretrained(mid)
    AutoModelForTokenClassification.from_pretrained(mid)
PY

# --- a partir daqui, offline e obrigatorio ---
# Estas variaveis fazem huggingface_hub falhar em vez de tentar egress.
# O compose ainda por cima remove a interface de rede (network_mode: none).
ENV HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    HF_HUB_DISABLE_TELEMETRY=1

# --- codigo ---
COPY . /app

# Usuario nao-root: o container manipula documentos, nao deve rodar como root.
RUN useradd --create-home --uid 1000 anon \
 && chmod -R a+rX /opt/models \
 && mkdir -p /app/out /app/data /app/eval/datasets \
 && chown -R anon:anon /app/out /app/data /app/eval
USER anon

ENTRYPOINT ["python", "-m", "anonimizador.cli"]
CMD ["--help"]
