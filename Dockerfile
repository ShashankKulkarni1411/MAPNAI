# MAPNAI — application image (ingestion + Agents 1-5)
#
# Every Python package version is pinned by requirements.lock, so the image is identical on
# every machine (no NumPy / PyTorch / FAISS mismatches).
#
#   docker compose build            build the image
#   docker compose run --rm mapnai  run ingestion + Agents 1-4 once
# See the "Docker" section of README.md for all commands.

# ── Stage 1: build a virtualenv with all dependencies ─────────────────────────
FROM python:3.11.9-slim-bookworm AS builder

# Compilers only for the few source-only packages (e.g. langdetect, sgmllib3k); not shipped.
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential \
 && rm -rf /var/lib/apt/lists/*

ENV VIRTUAL_ENV=/opt/venv \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
RUN python -m venv $VIRTUAL_ENV
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

COPY requirements.txt requirements.lock ./
RUN pip install --upgrade "pip==24.2" \
 && pip install -r requirements.txt -c requirements.lock \
        --extra-index-url https://download.pytorch.org/whl/cpu \
 # spaCy English model, version-matched to spaCy 3.8
 && pip install https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl

# ── Stage 2: runtime ─────────────────────────────────────────────────────────
FROM python:3.11.9-slim-bookworm

ENV VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    # Hugging Face models are cached here (baked-in embedding model + anything downloaded later)
    HF_HOME=/opt/hf-cache \
    TOKENIZERS_PARALLELISM=false

COPY --from=builder /opt/venv /opt/venv

# Bake the sentence-transformers embedding model (FAISS) into the image so runs work offline.
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"

WORKDIR /app
COPY . .

# models/, data/ and logs/ are mounted as volumes by docker-compose.yml.
# Agent 2's classifier downloads itself into models/classifier on first run
# (huggingface.co/satvik4577/mapnai-classifier); Agent 1's BERT NER model is optional —
# put it in models/mapnai-ner-bert, otherwise Agent 1 uses spaCy entities from ingestion.
RUN mkdir -p models data logs

CMD ["python", "run_mapnai.py"]
