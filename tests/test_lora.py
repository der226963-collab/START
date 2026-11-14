"""Tests for hand-rolled LoRA (mini_ai/gpt/lora.py).

Uses a tiny SmolLM2Model (small config, random weights) so the
tests run in seconds without the 360M pretrained weights.
"""
try:
    import torch
    import torch.nn.functional as F

    from mini_ai.gpt.lora import (
        LoRALinear,
        apply_lora,
        count_lora_parameters,
        load_lora_state_dict,
        lora_parameters,
        lora_state_dict,
    )
    from mini_ai.gpt.smollm2 import SmolLM2Config, SmolLM2Model

    HAS_TORCH = True
except ImportError:
    # System python has no torch; these tests run in the torch venv.
    # The module must still import cleanly so discovery does not fail.
    torch = None
    F = None
    HAS_TORCH = False


def _tiny_model():
    cfg = SmolLM2Config(
        vocab_size=256, hidden_size=64, intermediate_size=128,
        num_hidden_layers=2, num_attention_heads=4, num_key_value_heads=2,
        max_position_embeddings=128, tie_word_embeddings=True,
    )
    torch.manual_seed(0)
    return SmolLM2Model(cfg).to(torch.float32)


def test_lora_is_identity_at_init():
    model = _tiny_model()
    idx = torch.randint(0, 256, (2, 8))
    with torch.no_grad():
        before, _ = model(idx)
    apply_lora(model, r=4, alpha=8.0)
    with torch.no_grad():
        after, _ = model(idx)
    # B is zero at init, so the adapter adds exactly nothing.
    assert torch.equal(before, after), "LoRA changed the output at init"


def test_only_lora_params_trainable():
    model = _tiny_model()
    apply_lora(model, r=4, alpha=8.0)
    trainable = [n for n, p in model.named_parameters() if p.requires_grad]
    assert trainable, "no trainable parameters after apply_lora"
    assert all("lora_" in n for n in trainable), f"non-LoRA params trainable: {trainable}"
    n = count_lora_parameters(model)
    # 2 layers x (q 4*64+64*4, k 4*64+32*4, v same, o 4*64+64*4)
    # q: A 4x64=256, B 64x4=256 -> 512; k: 256+128=384; v: 384; o: 512.
    assert n == 2 * (512 + 384 + 384 + 512), f"unexpected LoRA param count {n}"


def test_training_step_updates_only_lora():
    model = _tiny_model()
    apply_lora(model, r=4, alpha=8.0)
    idx = torch.randint(0, 256, (2, 8))
    targets = torch.randint(0, 256, (2, 8))
    before_lora = {n: p.detach().clone() for n, p in model.named_parameters() if "lora_" in n}
    before_base = {n: p.detach().clone() for n, p in model.named_parameters() if "lora_" not in n}
    logits, _ = model(idx)
    loss = F.cross_entropy(logits.view(-1, logits.size(-1)), targets.view(-1))
    loss.backward()
    # Only LoRA params should have gradients.
    for n, p in model.named_parameters():
        if "lora_" in n:
            assert p.grad is not None, f"LoRA param {n} has no grad"
        else:
            assert p.grad is None, f"base param {n} has a grad"
    opt = torch.optim.AdamW(lora_parameters(model), lr=1e-3)
    opt.step()
    for n, p in model.named_parameters():
        if "lora_" in n:
            assert not torch.equal(p.detach(), before_lora[n]), f"LoRA param {n} did not move"
        else:
            assert torch.equal(p.detach(), before_base[n]), f"base param {n} moved"


def test_lora_save_load_roundtrip():
    model = _tiny_model()
    apply_lora(model, r=4, alpha=8.0)
    # Move the adapters off identity so the round-trip is meaningful.
    with torch.no_grad():
        for mod in model.modules():
            if isinstance(mod, LoRALinear):
                mod.lora_B.add_(0.01)
    state = lora_state_dict(model)
    model2 = _tiny_model()
    apply_lora(model2, r=4, alpha=8.0)
    idx = torch.randint(0, 256, (2, 8))
    with torch.no_grad():
        out_before, _ = model(idx)
    load_lora_state_dict(model2, state)
    with torch.no_grad():
        out_after, _ = model2(idx)
    # Same base weights (same seed) + same adapters -> same output.
    # (Both models were built with the same seed, so base weights match.)
    assert torch.allclose(out_before, out_after, atol=1e-5), "save/load changed the output"
