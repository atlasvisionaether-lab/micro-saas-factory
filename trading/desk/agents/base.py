"""Agent contract.

R1 analyze(bundle)            -> claims, written without seeing anyone else's (no anchoring)
R2 respond(bundle, others)    -> challenge / support messages on other agents' R1 claims
R3 defend(bundle, claim, ch)  -> defend or concede one challenge against this agent's claim

Agents are pure functions of the bundle: no I/O, no clock, no randomness.
"""

from ..schema import Message

# how much a conceded challenge cuts the claim's confidence
CONCEDE_FACTOR = {"info": 1.0, "warn": 0.6, "critical": 0.2}


class Agent:
    name = "agent"
    title = "Ajan"

    def analyze(self, b):
        return []

    def respond(self, b, others):
        return []

    def defend(self, b, claim, challenge):
        """Default: concede in proportion to the challenge's severity."""
        return self.concede(claim, challenge, "İtirazı kabul ediyorum; iddianın güveni düşürüldü.")

    # helpers -------------------------------------------------------------
    def msg(self, rnd, kind, topic, text, **kw):
        return Message(id="", round=rnd, agent=self.name, kind=kind, topic=topic, text=text, **kw)

    def claim(self, topic, text, **kw):
        return self.msg("R1", "claim", topic, text, **kw)

    def challenge(self, target, text, severity="warn", **kw):
        return self.msg("R2", "challenge", target.topic, text, replies_to=target.id, severity=severity,
                        stance="against" if target.stance == "for" else "neutral", **kw)

    def support(self, target, text, **kw):
        return self.msg("R2", "support", target.topic, text, replies_to=target.id, stance=target.stance, **kw)

    def concede(self, claim, challenge, text):
        conf = round(claim.confidence * CONCEDE_FACTOR[challenge.severity], 4)
        return self.msg("R3", "concede", claim.topic, text, replies_to=challenge.id, stance=claim.stance,
                        severity=challenge.severity, confidence=conf)

    def defend_keep(self, claim, challenge, text, evidence=None):
        return self.msg("R3", "defend", claim.topic, text, replies_to=challenge.id, stance=claim.stance,
                        severity=challenge.severity, confidence=claim.confidence, evidence=evidence or {})
