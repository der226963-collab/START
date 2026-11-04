"""Checks: training actually reduces loss, and the assistant learns."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from mini_ai.assistant import Assistant


def test_training_reduces_loss_and_learns():
    assistant = Assistant()
    losses = assistant.train(epochs=200)
    assert losses[-1] < losses[0], f"loss did not fall: {losses[0]} -> {losses[-1]}"
    assert "Hi" in assistant.reply("hello") or "tiny local" in assistant.reply("hello")
    assert assistant.reply("thank you").startswith("You're welcome")


if __name__ == "__main__":
    test_training_reduces_loss_and_learns()
    print("tests passed")
