"""Literature-tier conductance discount (Feature 2 P2, ADR-0013). Pure/offline."""

from backend.config import settings
from backend.db.queries.traversal import _base_conductance, _conductance


def test_literature_tier_is_discounted():
    props = {"combined_score": 0.8}
    base = _conductance("INTERACTS_WITH", props)
    assert base == 0.8
    lit = _conductance("INTERACTS_WITH", {**props, "provenance_tier": "literature"})
    assert lit == 0.8 * settings.LITERATURE_CONDUCTANCE_FACTOR


def test_absent_tier_is_canonical_noop():
    # No provenance_tier (canonical) -> conductance == base, no discount.
    for rel, props in [("IMPLICATED_IN", {}), ("CATALYSES", {}),
                       ("ASSOCIATED_WITH", {"p_value": 1e-20})]:
        assert _conductance(rel, props) == _base_conductance(rel, props)


def test_canonical_string_is_not_discounted():
    # Only the exact 'literature' tier is discounted; a stray value is treated canonical.
    props = {"combined_score": 0.8, "provenance_tier": "canonical"}
    assert _conductance("INTERACTS_WITH", props) == 0.8
