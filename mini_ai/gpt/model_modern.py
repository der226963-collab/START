"""Modern transformer variant: RMSNorm, RoPE, SwiGLU.

Original implementation of the published recipe used by modern
small models (LLaMA/Qwen-style): RMSNorm instead of LayerNorm,
rotary position embeddings instead of learned absolute positions,
and a gated SwiGLU feed-forward network instead of GELU.

This is NOT a new architecture claim. It is a small, readable
version of those three well-known changes, so this repo can
compare the 2017-style MiniGPT in model.py with a modern variant
on the same data, same size, same evaluation.

PCAC note, unchanged: this predicts text only. It does not
allocate, decide, or approve anything. Planning and decisions
stay in separate layers, with humans deciding.
"""
import math
from dataclasses import dataclass

import torch
import torch.nn as nn
import torch.nn.functional as F


@dataclass
class ModernConfig:
    vocab_size: int = 65
    block_size: int = 64
    n_layer: int = 2
    n_head: int = 4
    n_embd: int = 64
    dropout: float = 0.0
    # QK-norm (off by default, so old checkpoints still load):
    # RMSNorm on Q and K per head before attention scores.
    # It keeps attention logits from growing with scale, which
    # is why it helps larger / longer runs stay stable.
    qk_norm: bool = False
    # Weight tying (off by default, same compatibility reason):
    # the output head shares the token embedding matrix.
    tie_weights: bool = False


class RMSNorm(nn.Module):
    def __init__(self, dim, eps=1e-5):
        super().__init__()
        self.eps = eps
        self.weight = nn.Parameter(torch.ones(dim))

    def forward(self, x):
        norm = x * torch.rsqrt(x.pow(2).mean(dim=-1, keepdim=True) + self.eps)
        return norm * self.weight


def _rope_freqs(head_dim, max_len, device):
    inv_freq = 1.0 / (10000 ** (torch.arange(0, head_dim, 2, device=device).float() / head_dim))
    positions = torch.arange(max_len, device=device).float()
    freqs = torch.outer(positions, inv_freq)
    return torch.cos(freqs), torch.sin(freqs)


def _apply_rope(x, cos, sin):
    # x: (batch, heads, seq, head_dim), head_dim even
    x1 = x[..., 0::2]
    x2 = x[..., 1::2]
    cos = cos[: x.shape[2]].unsqueeze(0).unsqueeze(0)
    sin = sin[: x.shape[2]].unsqueeze(0).unsqueeze(0)
    out1 = x1 * cos - x2 * sin
    out2 = x1 * sin + x2 * cos
    out = torch.empty_like(x)
    out[..., 0::2] = out1
    out[..., 1::2] = out2
    return out


class ModernAttention(nn.Module):
    def __init__(self, config):
        super().__init__()
        assert config.n_embd % config.n_head == 0
        self.n_head = config.n_head
        self.head_dim = config.n_embd // config.n_head
        self.qkv = nn.Linear(config.n_embd, 3 * config.n_embd, bias=False)
        self.proj = nn.Linear(config.n_embd, config.n_embd, bias=False)
        self.qk_norm = config.qk_norm
        if self.qk_norm:
            self.q_norm = RMSNorm(self.head_dim)
            self.k_norm = RMSNorm(self.head_dim)
        self.dropout = nn.Dropout(config.dropout)
        self.register_buffer("mask", torch.tril(torch.ones(config.block_size, config.block_size)))

    def forward(self, x):
        batch, seq, embd = x.shape
        q, k, v = self.qkv(x).split(embd, dim=2)
        q = q.view(batch, seq, self.n_head, self.head_dim).transpose(1, 2)
        k = k.view(batch, seq, self.n_head, self.head_dim).transpose(1, 2)
        v = v.view(batch, seq, self.n_head, self.head_dim).transpose(1, 2)
        if self.qk_norm:
            q = self.q_norm(q)
            k = self.k_norm(k)
        cos, sin = _rope_freqs(self.head_dim, seq, x.device)
        q = _apply_rope(q, cos, sin)
        k = _apply_rope(k, cos, sin)
        # Fused scaled-dot-product attention (2026-11-04): same
        # causal math as the manual scores/mask above, but using
        # PyTorch's fused kernel where available, which is faster
        # on CPU as well as GPU. is_causal=True replaces the
        # manual mask; the old mask buffer is kept for
        # compatibility but no longer used here.
        out = F.scaled_dot_product_attention(
            q, k, v, is_causal=True,
            dropout_p=self.dropout.p if self.training else 0.0)
        out = out.transpose(1, 2).contiguous().view(batch, seq, embd)
        return self.proj(out)


class SwiGLU(nn.Module):
    def __init__(self, config):
        super().__init__()
        # 8/3 trick: three matrices instead of two, so hidden size
        # drops from 4x to about 8/3 x to keep parameter count close.
        hidden = int(2 * 4 * config.n_embd / 3)
        hidden = (hidden + 7) // 8 * 8
        self.w1 = nn.Linear(config.n_embd, hidden, bias=False)
        self.w3 = nn.Linear(config.n_embd, hidden, bias=False)
        self.w2 = nn.Linear(hidden, config.n_embd, bias=False)
        self.dropout = nn.Dropout(config.dropout)

    def forward(self, x):
        return self.dropout(self.w2(F.silu(self.w1(x)) * self.w3(x)))


class ModernBlock(nn.Module):
    def __init__(self, config):
        super().__init__()
        self.norm1 = RMSNorm(config.n_embd)
        self.attn = ModernAttention(config)
        self.norm2 = RMSNorm(config.n_embd)
        self.mlp = SwiGLU(config)

    def forward(self, x):
        x = x + self.attn(self.norm1(x))
        x = x + self.mlp(self.norm2(x))
        return x


class ModernGPT(nn.Module):
    def __init__(self, config):
        super().__init__()
        self.config = config
        self.token_emb = nn.Embedding(config.vocab_size, config.n_embd)
        self.blocks = nn.ModuleList([ModernBlock(config) for _ in range(config.n_layer)])
        self.norm_f = RMSNorm(config.n_embd)
        self.head = nn.Linear(config.n_embd, config.vocab_size, bias=False)
        self.apply(self._init_weights)
        if config.tie_weights:
            # Share storage, not just values: updates to the
            # embedding also update the head, and vice versa.
            self.head.weight = self.token_emb.weight

    @staticmethod
    def _init_weights(module):
        if isinstance(module, (nn.Linear, nn.Embedding)):
            nn.init.normal_(module.weight, mean=0.0, std=0.02)

    def forward(self, idx, targets=None):
        x = self.token_emb(idx)
        for block in self.blocks:
            x = block(x)
        logits = self.head(self.norm_f(x))
        loss = None
        if targets is not None:
            loss = F.cross_entropy(logits.view(-1, logits.size(-1)), targets.view(-1))
        return logits, loss

    @torch.no_grad()
    def generate(self, idx, max_new_tokens, temperature=1.0):
        self.eval()
        for _ in range(max_new_tokens):
            context = idx[:, -self.config.block_size:]
            logits, _ = self(context)
            next_logits = logits[:, -1, :] / max(temperature, 1e-6)
            if temperature == 0:
                nxt = next_logits.argmax(dim=-1, keepdim=True)
            else:
                nxt = torch.multinomial(F.softmax(next_logits, dim=-1), num_samples=1)
            idx = torch.cat([idx, nxt], dim=1)
        return idx

    def count_parameters(self):
        return sum(p.numel() for p in self.parameters())
