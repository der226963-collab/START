"""Tiny training data: a few examples per intent.

This is deliberately small. Add your own intents here — that is
how this starter becomes useful, instead of staying a demo.
"""

INTENTS = {
    "greeting": [
        "hello", "hi", "hey", "good morning", "good afternoon",
        "hello there", "hi there",
    ],
    "goodbye": [
        "bye", "goodbye", "see you later", "good night", "talk later",
    ],
    "help": [
        "help", "can you help me", "i need help", "what can you do",
        "how do you work",
    ],
    "planning": [
        "help me plan something", "i want to plan a project",
        "lets plan", "plan this with me", "make a plan",
    ],
    "thanks": [
        "thanks", "thank you", "that helps", "great thanks", "appreciated",
    ],
}

RESPONSES = {
    "greeting": "Hi — I'm a tiny local AI, still learning. Try asking me for help, or to plan something.",
    "goodbye": "Goodbye for now. Come back and teach me a new intent when you're ready.",
    "help": "I can classify what you mean into a few intents, and I'm built to be extended. Add examples in mini_ai/data.py, retrain, and I get smarter in a small, visible way.",
    "planning": "Good — let's plan in small steps. What is the goal, what is the first step, and what would 'done' look like? Tell me those three and I'll keep them in order.",
    "thanks": "You're welcome. Every example you add makes the next version a bit better.",
}
