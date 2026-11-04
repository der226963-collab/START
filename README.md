# AI Starter — a small, local, auditable beginning

This is a separate side project from the PCAC blueprint. It is not a
frontier chatbot, and it does not call an external AI API.

It is a minimal AI you can actually read, train, and change:

1. A tiny neural network written from scratch in NumPy (`mini_ai/neural_net.py`)
   — one hidden layer, ReLU, softmax, manual back-propagation.
2. A tiny intent classifier on top of it (`mini_ai/assistant.py`)
   — it learns a handful of intents from a few example sentences each.
3. A command-line chat loop (`main.py`) — type, get a response, type `quit`.

## Run it

```bash
cd ai-starter
pip install -r requirements.txt
python main.py
```

Try: `hello`, `can you help me plan something?`, `thanks`, `bye`

## Run the tests

```bash
python -m pytest tests/ -q
# or, without pytest:
python tests/test_neural_net.py
```

## How to grow it — in order

1. **Add intents:** add examples in `mini_ai/data.py`, retrain. This is
   the fastest way to make it yours.
2. **Understand the maths:** read the back-prop code in `neural_net.py`
   line by line, then look at the GitHub references below.
3. **Make it generate text, not just classify:** move from intents to a
   character-level language model (see microGPT / nanoGPT below).
4. **Make it useful locally:** plug a small open model in via Ollama or
   llama.cpp for real language, and keep this classifier as the
   small, auditable router in front of it. That matches the
   cooperative / local-first idea: small auditable models first,
   big models only where needed.

## GitHub references found useful (study, don't just copy)

- **Karpathy — micrograd / nanoGPT lineage:** the canonical
  from-scratch path. Start with autograd, then a tiny MLP, then a
  transformer. Notes repo:
  https://github.com/chizkidd/Karpathy-Neural-Networks-Zero-to-Hero
- **karpathy-microgpt** — a GPT in 243 lines of pure Python, no
  PyTorch, no NumPy, hand-rolled autograd, attention and Adam:
  https://github.com/kibotu/karpathy-microgpt
  Good next step after this starter if you want text generation
  from scratch.
- **LiteGPT** — a 124M small language model, pre-trained and
  fine-tuned, in the nanoGPT style:
  https://github.com/kmkrofficial/LiteGPT
  Good example of what "small but real" looks like after the toy stage.
- **Local AI assistants via Ollama:** for running a small model
  fully locally instead of training one:
  https://github.com/ritiksharma33/local-ai-assistant
  and for private retrieval (RAG) with local models:
  https://github.com/jonfairbanks/local-rag

Check each repo's licence before reusing its code. The code in
this folder is original and intentionally tiny.
