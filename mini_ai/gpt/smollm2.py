"""SmolLM2-360M: a pretrained medium model, loaded with our own code.

HuggingFaceTB/SmolLM2-360M (Apache 2.0), 361,821,120 parameters:
32 layers, hidden 960, 15 query heads / 5 key-value heads (GQA),
intermediate 2560, vocab 49,152, context 8192, RoPE theta 100000,
RMSNorm, SwiGLU, tied embeddings, BF16 weights.

This module implements the model from the published Llama-style
recipe (RMSNorm, rotary embeddings, gated SwiGLU) in this repo's
own code, reusing the RMSNorm in model_modern.py. It does NOT use
the transformers library for the model. Two small loader libraries
are used only to read standard file formats: safetensors (weights)
and tokenizers (tokenizer.json). The weights are loaded verbatim;
nothing is retrained here.

Two details that differ from this repo's ModernGPT and must not
be "fixed" by unifying them:
- RoPE here is the rotate-half form (HF Llama): the vector is
  split into halves, not interleaved pairs. ModernGPT uses the
  interleaved form. They are different conventions; the weights
  were trained with rotate-half, so this module uses rotate-half.
- Attention is grouped-query (GQA): 5 KV heads serve 15 Q heads.
  ModernGPT is plain multi-head (KV heads == Q heads).

PCAC note, unchanged: this predicts text only. It does not
allocate, decide, or approve anything. Planning and decisions
stay in separate layers, with humans deciding.
"""
import json
import math
from dataclasses import dataclass
from pathlib import Path

import torch
import torch.nn as nn
import torch.nn.functional as F

from mini_ai.gpt.model_modern import RMSNorm


@dataclass
class SmolLM2Config:
    vocab_size: int = 49152
    hidden_size: int = 960
    intermediate_size: int = 2560
    num_hidden_layers: int = 32
    num_attention_heads: int = 15
    num_key_value_heads: int = 5
    max_position_embeddings: int = 8192
    rms_norm_eps: float = 1e-5
    rope_theta: float = 100000.0
    tie_word_embeddings: bool = True
    eos_token_id: int = 0

    @property
    def head_dim(self):
        return self.hidden_size // self.num_attention_heads

    @property
    def kv_repeat(self):
        assert self.num_attention_heads % self.num_key_value_heads == 0
        return self.num_attention_heads // self.num_key_value_heads


def _rope_freqs(head_dim, theta, seq_len, device):
    """Frequencies for the rotate-half RoPE (HF Llama form).

    Returns cos, sin of shape (seq_len, head_dim // 2). Pair j
    (0 <= j < head_dim // 2) rotates by position * theta^(-2j/head_dim).
    """
    half = head_dim // 2
    inv_freq = 1.0 / (theta ** (torch.arange(0, head_dim, 2, device=device).float() / head_dim))
    positions = torch.arange(seq_len, device=device).float()
    angles = torch.outer(positions, inv_freq)
    return torch.cos(angles), torch.sin(angles)


def _apply_rope_llama(x, cos, sin):
    """Rotate-half RoPE: split the last dim into halves, not pairs.

    x: (batch, heads, seq, head_dim). cos/sin: (seq, head_dim // 2).
    First half: x1*cos - x2*sin. Second half: x1*sin + x2*cos.
    This is HF Llama's apply_rotary_pos_emb, and it differs from
    model_modern's interleaved form -- see the module docstring.
    """
    half = x.shape[-1] // 2
    x1 = x[..., :half]
    x2 = x[..., half:]
    # cos/sin are computed in fp32; cast to the input dtype so a BF16
    # model stays BF16 (otherwise Q/K promote to fp32 while V stays
    # BF16 and scaled_dot_product_attention refuses the mix).
    cos = cos.to(x.dtype).unsqueeze(0).unsqueeze(0)
    sin = sin.to(x.dtype).unsqueeze(0).unsqueeze(0)
    out1 = x1 * cos - x2 * sin
    out2 = x1 * sin + x2 * cos
    return torch.cat([out1, out2], dim=-1)


class SmolLM2Attention(nn.Module):
    def __init__(self, config):
        super().__init__()
        self.config = config
        self.n_head = config.num_attention_heads
        self.n_kv_head = config.num_key_value_heads
        self.head_dim = config.head_dim
        self.kv_repeat = config.kv_repeat
        self.q_proj = nn.Linear(config.hidden_size, self.n_head * self.head_dim, bias=False)
        self.k_proj = nn.Linear(config.hidden_size, self.n_kv_head * self.head_dim, bias=False)
        self.v_proj = nn.Linear(config.hidden_size, self.n_kv_head * self.head_dim, bias=False)
        self.o_proj = nn.Linear(self.n_head * self.head_dim, config.hidden_size, bias=False)

    def forward(self, x):
        batch, seq, _ = x.shape
        q = self.q_proj(x).view(batch, seq, self.n_head, self.head_dim).transpose(1, 2)
        k = self.k_proj(x).view(batch, seq, self.n_kv_head, self.head_dim).transpose(1, 2)
        v = self.v_proj(x).view(batch, seq, self.n_kv_head, self.head_dim).transpose(1, 2)
        cos, sin = _rope_freqs(self.head_dim, self.config.rope_theta, seq, x.device)
        q = _apply_rope_llama(q, cos, sin)
        k = _apply_rope_llama(k, cos, sin)
        if self.kv_repeat > 1:
            # Each KV head serves kv_repeat Q heads (grouped-query).
            k = k.repeat_interleave(self.kv_repeat, dim=1)
            v = v.repeat_interleave(self.kv_repeat, dim=1)
        out = F.scaled_dot_product_attention(q, k, v, is_causal=True)
        out = out.transpose(1, 2).contiguous().view(batch, seq, self.n_head * self.head_dim)
        return self.o_proj(out)


class SmolLM2MLP(nn.Module):
    def __init__(self, config):
        super().__init__()
        self.gate_proj = nn.Linear(config.hidden_size, config.intermediate_size, bias=False)
        self.up_proj = nn.Linear(config.hidden_size, config.intermediate_size, bias=False)
        self.down_proj = nn.Linear(config.intermediate_size, config.hidden_size, bias=False)

    def forward(self, x):
        return self.down_proj(F.silu(self.gate_proj(x)) * self.up_proj(x))


class SmolLM2Block(nn.Module):
    def __init__(self, config):
        super().__init__()
        self.input_layernorm = RMSNorm(config.hidden_size, eps=config.rms_norm_eps)
        self.self_attn = SmolLM2Attention(config)
        self.post_attention_layernorm = RMSNorm(config.hidden_size, eps=config.rms_norm_eps)
        self.mlp = SmolLM2MLP(config)

    def forward(self, x):
        x = x + self.self_attn(self.input_layernorm(x))
        x = x + self.mlp(self.post_attention_layernorm(x))
        return x


class SmolLM2Model(nn.Module):
    def __init__(self, config):
        super().__init__()
        self.config = config
        self.embed_tokens = nn.Embedding(config.vocab_size, config.hidden_size)
        self.layers = nn.ModuleList([SmolLM2Block(config) for _ in range(config.num_hidden_layers)])
        self.norm = RMSNorm(config.hidden_size, eps=config.rms_norm_eps)
        self.lm_head = nn.Linear(config.hidden_size, config.vocab_size, bias=False)
        if config.tie_word_embeddings:
            # Share storage, not just values (same pattern as
            # ModernGPT's tie_weights).
            self.lm_head.weight = self.embed_tokens.weight

    def forward(self, idx, targets=None):
        x = self.embed_tokens(idx)
        for block in self.layers:
            x = block(x)
        logits = self.lm_head(self.norm(x))
        loss = None
        if targets is not None:
            loss = F.cross_entropy(logits.view(-1, logits.size(-1)), targets.view(-1))
        return logits, loss

    @torch.no_grad()
    def generate(self, idx, max_new_tokens, temperature=0.7, eos_id=None, max_context=1024):
        self.eval()
        for _ in range(max_new_tokens):
            context = idx[:, -max_context:]
            logits, _ = self(context)
            next_logits = logits[:, -1, :] / max(temperature, 1e-6)
            if temperature == 0:
                nxt = next_logits.argmax(dim=-1, keepdim=True)
            else:
                nxt = torch.multinomial(F.softmax(next_logits, dim=-1), num_samples=1)
            idx = torch.cat([idx, nxt], dim=1)
            if eos_id is not None and int(nxt.item()) == eos_id:
                break
        return idx

    def count_parameters(self):
        return sum(p.numel() for p in self.parameters())


# HF safetensors name -> this module's state-dict name.
# Note: the file has NO lm_head.weight. HF's safetensors format stores
# a tied tensor once, so only model.embed_tokens.weight is present;
# the model's tie (lm_head.weight is embed_tokens.weight) makes the
# head share it. The loader adds the head key back from the embedding
# below, so load_state_dict(strict=True) still sees every key.
_NAME_MAP = {
    "model.embed_tokens.weight": "embed_tokens.weight",
    "model.norm.weight": "norm.weight",
}


def _layer_map(i):
    return {
        f"model.layers.{i}.input_layernorm.weight": f"layers.{i}.input_layernorm.weight",
        f"model.layers.{i}.self_attn.q_proj.weight": f"layers.{i}.self_attn.q_proj.weight",
        f"model.layers.{i}.self_attn.k_proj.weight": f"layers.{i}.self_attn.k_proj.weight",
        f"model.layers.{i}.self_attn.v_proj.weight": f"layers.{i}.self_attn.v_proj.weight",
        f"model.layers.{i}.self_attn.o_proj.weight": f"layers.{i}.self_attn.o_proj.weight",
        f"model.layers.{i}.post_attention_layernorm.weight": f"layers.{i}.post_attention_layernorm.weight",
        f"model.layers.{i}.mlp.gate_proj.weight": f"layers.{i}.mlp.gate_proj.weight",
        f"model.layers.{i}.mlp.up_proj.weight": f"layers.{i}.mlp.up_proj.weight",
        f"model.layers.{i}.mlp.down_proj.weight": f"layers.{i}.mlp.down_proj.weight",
    }


def load_pretrained(model_dir, dtype=torch.bfloat16):
    """Load SmolLM2-360M weights verbatim from a Hugging Face download.

    model_dir holds config.json + model.safetensors (+ tokenizer files).
    Returns (model, config). Raises if any weight is missing, unexpected,
    or the wrong shape, or if the tied head and embedding disagree.
    """
    from safetensors.torch import load_file

    model_dir = Path(model_dir)
    cfg_json = json.loads((model_dir / "config.json").read_text())
    config = SmolLM2Config(
        vocab_size=cfg_json["vocab_size"],
        hidden_size=cfg_json["hidden_size"],
        intermediate_size=cfg_json["intermediate_size"],
        num_hidden_layers=cfg_json["num_hidden_layers"],
        num_attention_heads=cfg_json["num_attention_heads"],
        num_key_value_heads=cfg_json["num_key_value_heads"],
        max_position_embeddings=cfg_json["max_position_embeddings"],
        rms_norm_eps=cfg_json["rms_norm_eps"],
        rope_theta=cfg_json["rope_theta"],
        tie_word_embeddings=cfg_json["tie_word_embeddings"],
        eos_token_id=cfg_json["eos_token_id"],
    )
    raw = load_file(str(model_dir / "model.safetensors"))
    mapping = dict(_NAME_MAP)
    for i in range(config.num_hidden_layers):
        mapping.update(_layer_map(i))
    unknown = sorted(set(raw) - set(mapping))
    missing = sorted(set(mapping) - set(raw))
    if unknown:
        raise ValueError(f"Unexpected weights in safetensors file: {unknown}")
    if missing:
        raise ValueError(f"Missing weights in safetensors file: {missing}")
    model = SmolLM2Model(config)
    state = {mapping[k]: v.to(dtype) for k, v in raw.items()}
    # The tied head: the file stores the embedding once, so point the
    # head at the same tensor (the model already ties them).
    state["lm_head.weight"] = state["embed_tokens.weight"]
    model.load_state_dict(state, strict=True)
    model = model.to(dtype)
    model.eval()
    return model, config


def load_tokenizer(model_dir):
    """Load the model's tokenizer.json exactly (tokenizers library)."""
    from tokenizers import Tokenizer

    return Tokenizer.from_file(str(Path(model_dir) / "tokenizer.json"))
