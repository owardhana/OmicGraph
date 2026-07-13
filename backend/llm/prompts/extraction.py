"""Prompt for the literature-extraction relation verdict (Feature 2, stage 3).

The endpoint kinds already pin the edge type (protein-protein -> INTERACTS_WITH,
gene-disease -> IMPLICATED_IN), so the model answers a near-binary: does THIS
sentence assert the relation, and with what polarity? It never invents biology or
chooses direction.
"""

# Human-readable relation phrasing per MVP edge type.
RELATION_DESC = {
    "INTERACTS_WITH": "physically interacts with / binds / forms a complex with",
    "IMPLICATED_IN": "is implicated in / associated with / contributes to",
}

EXTRACTION_SYSTEM_PROMPT = """You are a biomedical relation-extraction validator for \
OmicGraph. Given ONE sentence from a paper abstract and two named entities, decide \
whether the sentence ASSERTS the specified relationship between them.

Rules:
- Judge ONLY what THIS sentence states. Do not use outside knowledge.
- Negation ("does not interact", "no association", "failed to") -> polarity "negate".
- Hedging ("may", "might", "could", "suggests", "potential", "appears to") -> "hedge".
- A clear positive statement -> polarity "affirm".
- If the sentence does not state this relationship between the two entities at all, \
set asserted=false.
- confidence in [0,1]: how clearly the sentence supports the relationship.
- evidence_span: the shortest substring of the sentence that carries the relation.

Respond with ONLY a JSON object, no prose:
{"asserted": true|false, "polarity": "affirm"|"negate"|"hedge", "confidence": 0.0, "evidence_span": "..."}"""


def build_extraction_prompt(sentence: str, subject, obj, edge_type: str) -> str:
    """subject/obj are dictionary.Entry (or any obj with .canonical/.kind)."""
    desc = RELATION_DESC.get(edge_type, "is related to")
    return (
        f"Relationship to check: does {subject.canonical} ({subject.kind}) {desc} "
        f"{obj.canonical} ({obj.kind})?\n\n"
        f"Sentence:\n{sentence[:1500]}"
    )
