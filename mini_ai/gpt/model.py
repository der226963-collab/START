"""A small GPT-style transformer in PyTorch.

Architecture, in the order data flows through it — the same pattern
used by nanoGPT and the other from-scratch GPT repos on GitHub:
  token embedding + position embedding
  -> N pre-norm transformer blocks
     -> causal multi-head self-attention (a token can only look
        at itself and earlier tokens, never at the future)
     -> feed-forward network, 4x wider inside, then back
     -> residual connections around both, so gradients can flow
  -> final layer norm -> linear head -> logits for the next token

Pre-norm (norm before attention / feed-forward, not after) is the
choice those repos converge on: it trains more stably as you add
layers, which is exactly what 'larger' needs.

PCAC alignment, kept explicit: this is the language-assistance
layer only. It predicts text. It does not allocate food, energy,
housing, or care, and it does not decide anything. In PCAC terms,
allocation is checked by a separate planning / simulation layer
under hard limits, and decisions are made by a human assembly.
A language model that blurs those layers is a bug, not a feature.

This code is original, written for this repo. It needs PyTorch;
see requirements-gpt.txt. The v1 classifier still needs only NumPy.
"""
import math
from dataclasses import dataclass

import torch
import torch.nn as nn
import torch.nn.functional as F


@dataclass
class GPTConfig:
    vocab_size: int = 65
    block_size: int = 64      # longest context the model can see
    n_layer: int = 2          # tiny default: fast on a CPU, easy to test
    n_head: int = 4
    n_embd: int = 64
    dropout: float = 0.0


class CharTokenizer:
    """Character-level tokenizer: simple, no downloads, no BPE yet.

    BPE / word-piece tokenization is the next upgrade after this —
    it is what lets a real small model use a larger vocabulary
    efficiently. Characters are the right first step because the
    vocabulary is tiny and every step is visible.
    """

    def __init__(self, text):
        self.chars = sorted(set(text))
        self.stoi = {ch: i for i, ch in enumerate(self.chars)}
        self.itos = {i: ch for ch, i in self.stoi.items()}

    @classmethod
    def from_chars(cls, chars):
        """Rebuild a tokenizer from a saved vocab, in saved order.

        Use this when loading a checkpoint. Building from text sorts
        the characters, which would scramble a saved mapping if the
        saved order was not sorted.
        """
        tok = cls.__new__(cls)
        tok.chars = list(chars)
        tok.stoi = {ch: i for i, ch in enumerate(tok.chars)}
        tok.itos = {i: ch for ch, i in tok.stoi.items()}
        return tok

    def encode(self, text):
        return [self.stoi[ch] for ch in text if ch in self.stoi]

    def decode(self, ids):
        return "".join(self.itos[int(i)] for i in ids)

    def __len__(self):
        return len(self.chars)


class CausalSelfAttention(nn.Module):
    def __init__(self, config):
        super().__init__()
        assert config.n_embd % config.n_head == 0
        self.n_head = config.n_head
        self.head_dim = config.n_embd // config.n_head
        self.qkv = nn.Linear(config.n_embd, 3 * config.n_embd, bias=False)
        self.proj = nn.Linear(config.n_embd, config.n_embd)
        self.dropout = nn.Dropout(config.dropout)
        # Causal mask: position i may attend to positions <= i only.
        self.register_buffer(
            "mask", torch.tril(torch.ones(config.block_size, config.block_size))
        )

    def forward(self, x):
        batch, seq, embd = x.shape
        q, k, v = self.qkv(x).split(embd, dim=2)
        # (batch, heads, seq, head_dim)
        q = q.view(batch, seq, self.n_head, self.head_dim).transpose(1, 2)
        k = k.view(batch, seq, self.n_head, self.head_dim).transpose(1, 2)
        v = v.view(batch, seq, self.n_head, self.head_dim).transpose(1, 2)
        scores = q @ k.transpose(-2, -1) / math.sqrt(self.head_dim)
        scores = scores.masked_fill(self.mask[:seq, :seq] == 0, float("-inf"))
        weights = F.softmax(scores, dim=-1)
        weights = self.dropout(weights)
        out = weights @ v  # (batch, heads, seq, head_dim)
        out = out.transpose(1, 2).contiguous().view(batch, seq, embd)
        return self.proj(out)


class Block(nn.Module):
    def __init__(self, config):
        super().__init__()
        self.ln1 = nn.LayerNorm(config.n_embd)
        self.attn = CausalSelfAttention(config)
        self.ln2 = nn.LayerNorm(config.n_embd)
        self.mlp = nn.Sequential(
            nn.Linear(config.n_embd, 4 * config.n_embd),
            nn.GELU(),
            nn.Linear(4 * config.n_embd, config.n_embd),
            nn.Dropout(config.dropout),
        )

    def forward(self, x):
        x = x + self.attn(self.ln1(x))
        x = x + self.mlp(self.ln2(x))
        return x


class MiniGPT(nn.Module):
    def __init__(self, config):
        super().__init__()
        self.config = config
        self.token_emb = nn.Embedding(config.vocab_size, config.n_embd)
        self.pos_emb = nn.Embedding(config.block_size, config.n_embd)
        self.blocks = nn.ModuleList([Block(config) for _ in range(config.n_layer)])
        self.ln_f = nn.LayerNorm(config.n_embd)
        self.head = nn.Linear(config.n_embd, config.vocab_size, bias=False)
        self.apply(self._init_weights)

    @staticmethod
    def _init_weights(module):
        # GPT-style init: small normal weights, zero biases. The
        # default PyTorch init also works, but this makes training
        # behaviour reproducible across the small configs used here.
        if isinstance(module, (nn.Linear, nn.Embedding)):
            nn.init.normal_(module.weight, mean=0.0, std=0.02)
            if isinstance(module, nn.Linear) and module.bias is not None:
                nn.init.zeros_(module.bias)

    def forward(self, idx, targets=None):
        batch, seq = idx.shape
        positions = torch.arange(seq, device=idx.device)
        x = self.token_emb(idx) + self.pos_emb(positions)
        for block in self.blocks:
            x = block(x)
        logits = self.head(self.ln_f(x))
        loss = None
        if targets is not None:
            loss = F.cross_entropy(logits.view(-1, logits.size(-1)), targets.view(-1))
        return logits, loss

    @torch.no_grad()
    def generate(self, idx, max_new_tokens, temperature=1.0):
        """Extend idx by max_new_tokens, sampling at the given temperature.

        temperature=0 means greedy (always pick the most likely token).
        """
        self.eval()
        for _ in range(max_new_tokens):
            context = idx[:, -self.config.block_size:]
            logits, _ = self(context)
            next_logits = logits[:, -1, :] / max(temperature, 1e-6)
            if temperature == 0:
                nxt = next_logits.argmax(dim=-1, keepdim=True)
            else:
                probs = F.softmax(next_logits, dim=-1)
                nxt = torch.multinomial(probs, num_samples=1)
            idx = torch.cat([idx, nxt], dim=1)
        return idx

    def count_parameters(self):
        return sum(p.numel() for p in self.parameters())
