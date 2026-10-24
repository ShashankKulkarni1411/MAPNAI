# Colab: Bespoke-MiniCheck-7B ceiling (S5)

Status: **PENDING**. The project laptop has an RTX 3050 with 6 GB, and the model needs ≈ 15 GB of bf16 weights plus the vLLM KV cache. vLLM is Linux-only.

## Requirements

- A Colab runtime with **one A100 (40 or 80 GB)**. Smaller GPUs need a lower `max_model_len`, which changes the chunking and therefore the protocol. Do not do that for S5.
- A Hugging Face account that has **accepted the LLM-AggreFact terms** (`lytang/LLM-AggreFact`, gated, CC-BY-ND-4.0, evaluation only). Bespoke-MiniCheck-7B is CC BY-NC 4.0, so non-commercial use only.
- The dataset revision recorded in `research/experiments/data/MANIFEST.json` (Phase 2B).

## Steps (one Colab cell each)

```bash
pip install -q "minicheck[llm] @ git+https://github.com/Liyan06/MiniCheck.git@b58b9fa69acbd1015ec970fa65dd752413a053d2" "datasets==3.6.0" "scikit-learn==1.7.2"
python -c "import nltk; nltk.download('punkt_tab')"
huggingface-cli login            # paste a read token; the account must have accepted the LLM-AggreFact terms
```

```bash
# copy research/colab/run_bespoke.py into the Colab working directory, then:
python run_bespoke.py --tag colab-smoke --dataset-revision 981dfd0bd8e58e7238a9ab92b2e6ea44bce918e4 --limit 50   # 2-3 min sanity run
python run_bespoke.py --tag colab-full  --dataset-revision 981dfd0bd8e58e7238a9ab92b2e6ea44bce918e4              # ≈ 1 h on an A100
```

Copy `outputs/bespoke_aggrefact_colab-full.json` and `outputs/bespoke_preds_colab-full.jsonl.gz` back into `research/experiments/results/`. The script records the vLLM, torch and transformers versions it used (`pip_freeze`).

## Security review of the remote code (R8)

`trust_remote_code` is required (`InternLM2ForCausalLM`). The files at revision `1ed7786bcda3fa1dc35f7c4ed9e3f36b785d33b8` were downloaded and scanned on 2026-10-23:

| File | Lines | sha256 |
|---|---|---|
| `configuration_internlm2.py` | 180 | `89863f76…fd856` |
| `modeling_internlm2.py` | 1,800 | `1b781ec7…bad005` |
| `tokenization_internlm2.py` | 236 | `444d4c2b…5eef` |
| `tokenization_internlm2_fast.py` | 214 | `1fe5f033…ae10` |

Imports are limited to torch, transformers, einops, sentencepiece, tokenizers, the optional flash_attn, and the stdlib modules `math`, `queue`, `threading`, `os` and `shutil.copyfile`. There are no network calls, `exec`/`eval`, subprocess, pickle or `torch.load`. The only file write is the standard `save_vocabulary`. `threading`/`queue` serve the chat-streaming helper.

**Caveat:** `config.json` `auto_map["AutoModel"]` points to code in another, unpinned repository (`internlm/internlm2_5-7b-chat`). The script never calls `AutoModel` and verifies the four hashes above before loading.
