"""Hand-rolled LoRA (Low-Rank Adaptation) for this repo's models.

No external LoRA library is used (peft is not installed, and this
project keeps its training code in-house). LoRA freezes the base
weights and trains only small low-rank adapter matrices, so a
360M-parameter model can be fine-tuned on CPU: the base stays in
BF16 and frozen, and only the adapters (well under 1% of the
parameters) take gradients and optimizer state.

For a linear layer W (out x in), LoRA adds a low-rank delta:
    delta(x) = (alpha / r) * B @ A @ x
where A is (r x in), B is (out x r), r is the rank. A is initialised
with small random values and B with zeros, so the adapter is the
identity at the start: the model is unchanged until training moves B.

The base linear is frozen and stays in its dtype (BF16 for SmolLM2).
The adapter matrices are FP32, and the adapter branch is computed
in FP32 (input cast up, result cast back) so gradients are stable.
Only the adapter parameters require gradients.
"""
import math

import torch
import torch.nn as nn
import torch.nn.functional as F


class LoRALinear(nn.Module):
    """An nn.Linear with a low-rank adapter added to its output.

    Wraps an existing linear (kept frozen) and adds trainable A, B.
    """

    def __init__(self, base, r=8, alpha=16.0):
        super().__init__()
        if not isinstance(base, nn.Linear):
            raise TypeError("LoRALinear wraps an nn.Linear")
        if r <= 0:
            raise ValueError("LoRA rank r must be positive")
        self.base = base
        self.r = r
        self.alpha = alpha
        self.scaling = alpha / r
        in_f = base.in_features
        out_f = base.out_features
        # A: (r, in), B: (out, r). A small random, B zero -> identity.
        self.lora_A = nn.Parameter(torch.empty(r, in_f, dtype=torch.float32))
        self.lora_B = nn.Parameter(torch.zeros(out_f, r, dtype=torch.float32))
        nn.init.kaiming_uniform_(self.lora_A, a=math.sqrt(5))
        # Freeze the base weights: the adapter is the only trainable part.
        for p in self.base.parameters():
            p.requires_grad_(False)

    def forward(self, x):
        out = self.base(x)
        # Adapter branch in FP32, cast back to the base dtype.
        x32 = x.to(torch.float32)
        delta = F.linear(F.linear(x32, self.lora_A), self.lora_B)
        return out + self.scaling * delta.to(out.dtype)

    def adapter_state(self):
        return {"lora_A": self.lora_A.detach().clone(),
                "lora_B": self.lora_B.detach().clone()}


def _set_child(parent, name, child):
    """Set a (possibly nested) child module by dotted name."""
    parts = name.split(".")
    for p in parts[:-1]:
        parent = getattr(parent, p)
    setattr(parent, parts[-1], child)


def apply_lora(model, target_suffixes=("self_attn.q_proj", "self_attn.k_proj",
                                       "self_attn.v_proj", "self_attn.o_proj"),
               r=8, alpha=16.0):
    """Replace matching nn.Linear layers with LoRALinear adapters.

    target_suffixes are matched against the end of each module's
    dotted name (e.g. "layers.3.self_attn.q_proj" ends with
    "self_attn.q_proj"). Every other parameter in the model is
    frozen. Returns the list of LoRA modules added.

    The base model's forward is unchanged (adapters start as
    identity), so this is safe to call before or after loading
    pretrained weights.
    """
    # Freeze everything first; LoRALinear re-freezes its base.
    for p in model.parameters():
        p.requires_grad_(False)
    added = []
    # Collect first (do not mutate while iterating named_modules).
    matches = []
    for name, mod in model.named_modules():
        if isinstance(mod, nn.Linear) and name.endswith(target_suffixes):
            matches.append(name)
    for name in matches:
        parent = model
        parts = name.split(".")
        for p in parts[:-1]:
            parent = getattr(parent, p)
        base = getattr(parent, parts[-1])
        lora = LoRALinear(base, r=r, alpha=alpha)
        setattr(parent, parts[-1], lora)
        added.append(lora)
    if not added:
        raise ValueError(f"no linear layers matched {target_suffixes}")
    return added


def lora_parameters(model):
    """All trainable (LoRA adapter) parameters of a LoRA-adapted model."""
    return [p for n, p in model.named_parameters() if "lora_" in n and p.requires_grad]


def count_lora_parameters(model):
    return sum(p.numel() for p in lora_parameters(model))


def lora_state_dict(model):
    """Only the adapter weights, keyed by module name.

    Small (a few MB at rank 8), so adapters can be saved and pushed
    without the base weights, which stay local.
    """
    state = {}
    for name, mod in model.named_modules():
        if isinstance(mod, LoRALinear):
            state[f"{name}.lora_A"] = mod.lora_A.detach().clone()
            state[f"{name}.lora_B"] = mod.lora_B.detach().clone()
    return state


def load_lora_state_dict(model, state):
    """Load adapter weights into a LoRA-adapted model (strict)."""
    for name, mod in model.named_modules():
        if isinstance(mod, LoRALinear):
            a = state.get(f"{name}.lora_A")
            b = state.get(f"{name}.lora_B")
            if a is None or b is None:
                raise ValueError(f"missing adapter weights for {name}")
            if a.shape != mod.lora_A.shape or b.shape != mod.lora_B.shape:
                raise ValueError(f"adapter shape mismatch for {name}")
            mod.lora_A.data.copy_(a)
            mod.lora_B.data.copy_(b)
    # Any extra keys in state are an error (strict load).
    known = {f"{n}.lora_A" for n, m in model.named_modules()
             if isinstance(m, LoRALinear)}
    known |= {f"{n}.lora_B" for n, m in model.named_modules()
              if isinstance(m, LoRALinear)}
    extra = sorted(set(state) - known)
    if extra:
        raise ValueError(f"unexpected adapter weights: {extra}")


def apply_adapter_checkpoint(model, checkpoint_path):
    """Apply LoRA to a base model and load adapter weights from a
    train_smollm2_lora.py checkpoint (checkpoint.pt).

    The rank, alpha, and target modules are read from the
    checkpoint's recorded training args, so the adapter is applied
    exactly as it was trained. The base weights are untouched.
    Returns the adapted model.
    """
    ckpt = torch.load(checkpoint_path, map_location="cpu", weights_only=False)
    if "adapter" not in ckpt or "args" not in ckpt:
        raise ValueError(f"{checkpoint_path} is not a LoRA checkpoint "
                         "(expected 'adapter' and 'args' keys)")
    a = ckpt["args"]
    suffixes = tuple(f"self_attn.{t}_proj" for t in a["target"].split(","))
    apply_lora(model, target_suffixes=suffixes, r=a["rank"], alpha=a["alpha"])
    load_lora_state_dict(model, ckpt["adapter"])
    return model
