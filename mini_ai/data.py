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
        "plan food for a neighbourhood", "plan energy for a community",
        "plan housing and care together",
    ],
    "explain_ai": [
        "what is this ai for", "how should ai be used",
        "who decides", "who makes the decision",
        "is the ai in charge", "what can this ai not do",
    ],
    "thanks": [
        "thanks", "thank you", "that helps", "great thanks", "appreciated",
    ],
}

RESPONSES = {
    "greeting": "Hi — I'm a tiny local AI, still learning. Try asking me for help, or to plan something.",
    "goodbye": "Goodbye for now. Come back and teach me a new intent when you're ready.",
    "help": "I can classify what you mean into a few intents, and I'm built to be extended. Add examples in mini_ai/data.py, retrain, and I get smarter in a small, visible way.",
    "planning": "Good — let's plan in small steps, the way a community assembly would. What need are we meeting, within what hard limits — land, water, energy, carbon — and with what labour and care shared fairly? Then: what is the first step, who does it, and what would 'done' look like? I can help draft and check the plan. People decide, and a separate planning calculation checks whether the numbers actually fit.",
    "explain_ai": "This is narrow AI, for assistance only. It can draft, summarise, and help check a plan, but it does not allocate food, energy, housing, or care, and it does not decide. A human assembly sets the goals and limits, a separate planning layer checks allocations, and people make the final decision.",
    "thanks": "You're welcome. Every example you add makes the next version a bit better.",
}
