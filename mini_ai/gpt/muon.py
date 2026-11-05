"""Muon optimizer, small readable version.

Muon (from the modded-nanogpt / KellerJordan work, itself based on
the Muon optimizer paper) updates 2D weight matrices with an
orthogonalized gradient instead of Adam's per-coordinate scaling.
The orthogonalization is Newton-Schulz iteration, the standard
published recipe: it makes the update matrix close to orthogonal,
so every direction in the weight matrix moves by a similar amount,
instead of Adam's coordinate-wise rescaling.

Use it only for hidden 2D weights. Embeddings, the output head,
biases and norms stay on AdamW — that split is the standard
Muon recipe, because Muon is designed for matrices, not vectors.

This is a CPU-friendly piece: it needs no GPU-only kernels
(FlashAttention, FP8 matmul) and no distributed reduce-scatter.
It is slower per step than AdamW on CPU because Newton-Schulz
does a few small matrix multiplications, but it is a real
optimizer change, not a claim about speed.
"""
import torch
from torch.optim import Optimizer


def orthogonalize(g, steps=5):
    """Return a near-orthogonal matrix with the same shape as g.

    Newton-Schulz, coefficients from the published Muon recipe
    (KellerJordan/Muon, MIT licence — checked 2026-11-04; our
    code here is an original implementation of the published
    formulas, not a copy of that file):
    a=3.4445, b=-4.7750, c=2.0315. The input is first scaled by
    its Frobenius norm, then iterated as
    X <- a*X + (b*(X X^T) + c*(X X^T)^2) @ X, with X transposed
    first if it is tall, so the small side is used. This form
    avoids building an explicit identity matrix.
    """
    if g.ndim != 2:
        raise ValueError("Muon orthogonalization needs a 2D matrix")
    a, b, c = (3.4445, -4.7750, 2.0315)
    transposed = g.shape[0] > g.shape[1]
    x = g.T if transposed else g
    x = x / (x.norm() + 1e-7)
    for _ in range(steps):
        gram = x @ x.T
        x = a * x + (b * gram + c * gram @ gram) @ x
    return x.T if transposed else x


class Muon(Optimizer):
    """Muon, aligned to the canonical KellerJordan recipe.

    Changes from our first version (2026-11-04, recorded here
    so old runs are comparable):
    - Nesterov momentum is now on by default, matching the
      canonical default: buf = momentum*buf + (1-momentum)*g,
      then update = (1-momentum)*g + momentum*buf, before
      orthogonalization.
    - Scaling is now the canonical sqrt(max(1, rows/cols)),
      not our earlier 0.2*sqrt(max(rows, cols)). For a square
      matrix the scale is 1.0, so the learning rate is now
      in spectral-norm units directly — a Muon lr of 0.02
      (canonical default) is the intended value, not 3e-3.
      train_gpt.py --muon-lr exists for exactly this choice.
    """

    def __init__(self, params, lr=0.02, momentum=0.95, weight_decay=0.0,
                 nesterov=True):
        super().__init__(params, dict(lr=lr, momentum=momentum,
                                      weight_decay=weight_decay,
                                      nesterov=nesterov))

    @torch.no_grad()
    def step(self, closure=None):
        loss = None
        if closure is not None:
            loss = closure()
        for group in self.param_groups:
            lr = group["lr"]
            momentum = group["momentum"]
            wd = group["weight_decay"]
            nesterov = group.get("nesterov", True)
            for p in group["params"]:
                if p.grad is None:
                    continue
                g = p.grad
                state = self.state[p]
                if "momentum_buffer" not in state:
                    state["momentum_buffer"] = torch.zeros_like(p)
                buf = state["momentum_buffer"]
                buf.mul_(momentum).add_(g, alpha=1 - momentum)
                update = g.lerp(buf, momentum) if nesterov else buf
                update = orthogonalize(update)
                # Canonical scaling: sqrt(max(1, rows/cols)).
                scale = max(1.0, p.shape[0] / p.shape[1]) ** 0.5
                if wd:
                    p.mul_(1 - lr * wd)
                p.add_(update, alpha=-lr * scale)
        return loss
