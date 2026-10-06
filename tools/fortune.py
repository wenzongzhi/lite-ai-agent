import random

CARDS = ("The Fool", "The Magician", "The High Priestess", "The Empress", "The Emperor",
         "The Lovers", "The Chariot", "Strength", "The Hermit", "Wheel of Fortune",
         "Justice", "The Hanged Man", "Temperance", "The Star", "The Moon", "The Sun", "The World")


def fortune_telling(topic: str, method: str = "tarot") -> dict:
    """Python draws the result; the model only interprets it for entertainment."""
    rng = random.SystemRandom()
    draw = rng.choice(CARDS) if method == "tarot" else rng.choice(("Reflect", "Explore", "Be patient", "Take a small step"))
    return {"topic": topic, "method": method, "draw": draw, "entertainment_only": True,
            "notice": "Simulated entertainment only; not a prediction or advice for medical, legal, financial, or safety decisions."}
