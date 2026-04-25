import os

AGENT_INTENTS: frozenset[str] = frozenset(
    i.strip()
    for i in os.getenv("AGENT_INTENTS", "CHECKOUT,PAYMENT_LOG").split(",")
    if i.strip()
)
