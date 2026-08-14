"""
Tests for scripts/rebuild_search_index.py -- the fix for a real, live-reproduced
gap: `openmetadata_search`'s data directory is a tmpfs mount by design, so
`table_search_index` doesn't exist at all until something repopulates it, and
nothing did on a bare `docker compose down`/`up` with no pipeline re-run.

All offline: api_get/api_post are monkeypatched, matching the shared-client
mocking pattern already used for scripts that call OpenMetadata's REST API.
Sleeps are patched out so the polling-loop tests run in milliseconds, not
real wall-clock seconds.
"""

import scripts.rebuild_search_index as ris


def _run(status="success", start_time=200, failed=0, total=165):
    return {
        "status": status,
        "startTime": start_time,
        "endTime": start_time + 3000,
        "successContext": {"stats": {"jobStats": {"totalRecords": total, "failedRecords": failed}}},
    }


def test_succeeds_once_a_new_success_run_appears(monkeypatch):
    # Baseline (pre-trigger) run, then the real run this call triggered.
    calls = {"n": 0}

    def fake_get(endpoint):
        calls["n"] += 1
        return {"data": [_run(start_time=100)]} if calls["n"] == 1 else {"data": [_run(start_time=200)]}

    monkeypatch.setattr(ris, "api_get", fake_get)
    monkeypatch.setattr(ris, "api_post", lambda endpoint: {"status": "success"})
    monkeypatch.setattr(ris.time, "sleep", lambda s: None)

    assert ris.rebuild_search_index() is True


def test_waits_through_a_running_status_before_success(monkeypatch):
    # Baseline, then a "running" poll, then "success" -- the loop must not
    # declare success on the first poll after the trigger just because a run
    # with a new startTime exists; it must wait for a terminal status.
    responses = iter([
        {"data": [_run(status="success", start_time=100)]},   # baseline
        {"data": [_run(status="running", start_time=200)]},   # still going
        {"data": [_run(status="running", start_time=200)]},   # still going
        {"data": [_run(status="success", start_time=200)]},   # done
    ])
    monkeypatch.setattr(ris, "api_get", lambda endpoint: next(responses))
    monkeypatch.setattr(ris, "api_post", lambda endpoint: {"status": "success"})
    monkeypatch.setattr(ris.time, "sleep", lambda s: None)

    assert ris.rebuild_search_index() is True


def test_fails_on_a_terminal_non_success_status(monkeypatch):
    responses = iter([
        {"data": [_run(status="success", start_time=100)]},
        {"data": [_run(status="failed", start_time=200)]},
    ])
    monkeypatch.setattr(ris, "api_get", lambda endpoint: next(responses))
    monkeypatch.setattr(ris, "api_post", lambda endpoint: {"status": "success"})
    monkeypatch.setattr(ris.time, "sleep", lambda s: None)

    assert ris.rebuild_search_index() is False


def test_fails_on_partial_failure_even_though_status_is_success(monkeypatch):
    # A run can report status=success at the top level while some records
    # still failed -- this must not be reported as a clean rebuild.
    responses = iter([
        {"data": [_run(status="success", start_time=100)]},
        {"data": [_run(status="success", start_time=200, failed=3)]},
    ])
    monkeypatch.setattr(ris, "api_get", lambda endpoint: next(responses))
    monkeypatch.setattr(ris, "api_post", lambda endpoint: {"status": "success"})
    monkeypatch.setattr(ris.time, "sleep", lambda s: None)

    assert ris.rebuild_search_index() is False


def test_fails_closed_when_the_trigger_call_itself_fails(monkeypatch):
    # api_post/api_get return None on a connection failure (see
    # _openmetadata_client._request's documented contract) -- this must not
    # be mistaken for an empty-but-successful response.
    monkeypatch.setattr(ris, "api_get", lambda endpoint: None)
    monkeypatch.setattr(ris, "api_post", lambda endpoint: None)
    monkeypatch.setattr(ris.time, "sleep", lambda s: None)

    assert ris.rebuild_search_index() is False


def test_times_out_rather_than_hanging_forever(monkeypatch):
    # The app never reports a run newer than the baseline -- must give up
    # after POLL_TIMEOUT_SECONDS rather than looping indefinitely.
    monkeypatch.setattr(ris, "api_get", lambda endpoint: {"data": [_run(start_time=100)]})
    monkeypatch.setattr(ris, "api_post", lambda endpoint: {"status": "success"})
    monkeypatch.setattr(ris, "POLL_TIMEOUT_SECONDS", 1)
    monkeypatch.setattr(ris, "POLL_INTERVAL_SECONDS", 0.1)
    monkeypatch.setattr(ris.time, "sleep", lambda s: None)

    assert ris.rebuild_search_index() is False


def test_idempotent_when_the_app_has_never_run_before(monkeypatch):
    # First-ever trigger on a fresh deployment: no prior run exists at all
    # (api_get returns no data), not just a differently-timestamped one.
    responses = iter([
        {"data": []},
        {"data": [_run(status="success", start_time=200)]},
    ])
    monkeypatch.setattr(ris, "api_get", lambda endpoint: next(responses))
    monkeypatch.setattr(ris, "api_post", lambda endpoint: {"status": "success"})
    monkeypatch.setattr(ris.time, "sleep", lambda s: None)

    assert ris.rebuild_search_index() is True
