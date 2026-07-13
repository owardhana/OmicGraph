"""Admin gate decision (ADR-0014 §3 + ADR-0017 fail-closed).

Pure-function tests — no app boot, no Neo4j — so they run fast under the
iCloud-synced tree where full pytest collection crawls.
"""

from backend.api.routes.admin import _admin_denial


def test_no_token_dev_is_open():
    # Empty ADMIN_TOKEN + not fail-closed → local single-user dev convenience.
    assert _admin_denial("", None, False) is None
    assert _admin_denial("", "anything", False) is None


def test_no_token_fail_closed_refuses():
    # ADR-0017: empty token on a public host must REFUSE, not fall open.
    status, _ = _admin_denial("", None, True)
    assert status == 503
    status, _ = _admin_denial("", "anything", True)
    assert status == 503


def test_configured_token_requires_match():
    assert _admin_denial("s3cret", None, False)[0] == 401
    assert _admin_denial("s3cret", "wrong", False)[0] == 401
    assert _admin_denial("s3cret", "wrong", True)[0] == 401  # fail_closed irrelevant once set


def test_configured_token_match_allows():
    assert _admin_denial("s3cret", "s3cret", False) is None
    assert _admin_denial("s3cret", "s3cret", True) is None
