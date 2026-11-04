"""Train the tiny assistant, then chat with it. Type 'quit' to stop."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from mini_ai.assistant import Assistant


def main():
    assistant = Assistant()
    losses = assistant.train(epochs=300, verbose=True)
    print(f"\nTrained. Loss: {losses[0]:.4f} -> {losses[-1]:.4f}")
    print("Tiny AI ready. Type 'quit' to stop.\n")
    while True:
        try:
            text = input("you: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nbye")
            break
        if text.lower() in ("quit", "exit", "bye"):
            print("assistant: Goodbye for now.")
            break
        if text:
            print(f"assistant: {assistant.reply(text)}")


if __name__ == "__main__":
    main()
