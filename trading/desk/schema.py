"""The message every agent writes. One JSON line per message in transcript.jsonl."""

from dataclasses import asdict, dataclass, field

ROUNDS = ("R0", "R1", "R2", "R3", "R4")
KINDS = ("gate", "claim", "challenge", "support", "defend", "concede", "decision")
STANCES = ("for", "against", "neutral")       # relative to taking the trade
SEVERITIES = ("info", "warn", "critical")      # critical = veto


@dataclass
class Message:
    id: str
    round: str
    agent: str
    kind: str
    topic: str
    text: str
    stance: str = "neutral"
    severity: str = "info"
    confidence: float = 0.5
    evidence: dict = field(default_factory=dict)
    replies_to: str = None

    def __post_init__(self):
        if self.round not in ROUNDS:
            raise ValueError("bad round %r" % self.round)
        if self.kind not in KINDS:
            raise ValueError("bad kind %r" % self.kind)
        if self.stance not in STANCES:
            raise ValueError("bad stance %r" % self.stance)
        if self.severity not in SEVERITIES:
            raise ValueError("bad severity %r" % self.severity)
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be in [0, 1]")
        if self.kind in ("challenge", "support", "defend", "concede") and not self.replies_to:
            raise ValueError("%s needs replies_to" % self.kind)

    def to_dict(self):
        return asdict(self)
