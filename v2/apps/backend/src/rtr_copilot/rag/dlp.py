import re

from rtr_copilot.rag.models import DLPDecision

SENSITIVE_PATTERNS = {
    "dlp.credential": re.compile(
        r"(?i)(password|secret|api[_ -]?key|access[_ -]?token)\s*[:=]\s*\S+",
    ),
    "dlp.private_key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "dlp.personal_identifier": re.compile(
        r"\b(?:\d{9}|\d{12})\b",
    ),
}


class ProviderPolicy:
    def __init__(
        self,
        *,
        mode: str = "local",
        external_allowlist: frozenset[str] = frozenset(),
    ) -> None:
        self.mode = mode
        self.external_allowlist = external_allowlist

    def metadata_allowed(self, classification: str) -> bool:
        if self.mode == "local":
            return True
        return classification in self.external_allowlist

    def inspect(self, text: str, *, classification: str) -> DLPDecision:
        rules: list[str] = []
        if not self.metadata_allowed(classification):
            rules.append("provider.classification_denied")
        rules.extend(
            rule_id
            for rule_id, pattern in SENSITIVE_PATTERNS.items()
            if pattern.search(text)
        )
        return DLPDecision(
            allow=not rules,
            rule_ids=rules,
            redacted=False,
            text=text if not rules else None,
        )

    def inspect_context(self, serialized: str, classifications: set[str]) -> DLPDecision:
        rules: list[str] = []
        if any(not self.metadata_allowed(item) for item in classifications):
            rules.append("provider.context_classification_denied")
        rules.extend(
            rule_id
            for rule_id, pattern in SENSITIVE_PATTERNS.items()
            if pattern.search(serialized)
        )
        return DLPDecision(
            allow=not rules,
            rule_ids=sorted(set(rules)),
            text=serialized if not rules else None,
        )
