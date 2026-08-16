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

import pytest

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


# ---------------------------------------------------------------------------
# index_has_data() -- the real-query health check the watch loop uses,
# instead of trusting a cached exit code from a previous run (the exact gap
# that let the index stay silently empty after a real host reboot: the
# previous one-shot `restart: "no"` container's success from days earlier
# meant nothing once openmetadata_search's tmpfs was wiped by a fresh start).
# ---------------------------------------------------------------------------


def test_index_has_data_true_when_search_returns_hits(monkeypatch):
    calls = []

    def fake_get(endpoint):
        calls.append(endpoint)
        return {"hits": {"hits": [{"_source": {"name": "deposit_account"}}]}}

    monkeypatch.setattr(ris, "api_get", fake_get)
    assert ris.index_has_data() is True
    assert "index=table_search_index" in calls[0]


def test_index_has_data_false_when_no_hits(monkeypatch):
    monkeypatch.setattr(ris, "api_get", lambda endpoint: {"hits": {"hits": []}})
    assert ris.index_has_data() is False


def test_index_has_data_false_on_missing_index_error(monkeypatch):
    # api_get returns None on an HTTP error (per _openmetadata_client's
    # documented contract) -- e.g. the real index_not_found_exception 500.
    monkeypatch.setattr(ris, "api_get", lambda endpoint: None)
    assert ris.index_has_data() is False


def test_index_has_data_false_on_malformed_response(monkeypatch):
    monkeypatch.setattr(ris, "api_get", lambda endpoint: {"unexpected": "shape"})
    assert ris.index_has_data() is False


# ---------------------------------------------------------------------------
# watch() -- the long-running loop that replaced the one-shot container.
# Runs exactly one iteration per call by making time.sleep raise, so these
# stay fast and deterministic instead of actually looping.
# ---------------------------------------------------------------------------


class _StopLoop(Exception):
    pass


def test_watch_skips_rebuild_when_index_is_already_healthy(monkeypatch):
    rebuild_called = []
    monkeypatch.setattr(ris, "index_has_data", lambda: True)
    monkeypatch.setattr(ris, "rebuild_search_index", lambda: rebuild_called.append(1) or True)
    monkeypatch.setattr(ris, "_touch_heartbeat", lambda: None)
    monkeypatch.setattr(ris.time, "sleep", lambda s: (_ for _ in ()).throw(_StopLoop))

    with pytest.raises(_StopLoop):
        ris.watch()
    assert rebuild_called == [], "watch() must not trigger a reindex when the index is already healthy"


def test_watch_heals_when_index_is_empty(monkeypatch):
    rebuild_called = []
    monkeypatch.setattr(ris, "index_has_data", lambda: False)
    monkeypatch.setattr(ris, "rebuild_search_index", lambda: rebuild_called.append(1) or True)
    monkeypatch.setattr(ris, "_touch_heartbeat", lambda: None)
    monkeypatch.setattr(ris.time, "sleep", lambda s: (_ for _ in ()).throw(_StopLoop))

    with pytest.raises(_StopLoop):
        ris.watch()
    assert rebuild_called == [1], "watch() must trigger exactly one reindex when the index check fails"


def test_watch_survives_an_exception_in_the_health_check(monkeypatch):
    # A watch loop that dies on a transient error stops healing forever with
    # nothing left to notice -- it must log and continue to the next
    # interval, not propagate.
    def boom():
        raise RuntimeError("transient network blip")

    monkeypatch.setattr(ris, "index_has_data", boom)
    monkeypatch.setattr(ris, "_touch_heartbeat", lambda: None)
    monkeypatch.setattr(ris.time, "sleep", lambda s: (_ for _ in ()).throw(_StopLoop))

    with pytest.raises(_StopLoop):
        ris.watch()  # must reach the sleep (and raise _StopLoop), not RuntimeError


def test_watch_touches_heartbeat_every_iteration(monkeypatch):
    heartbeats = []
    monkeypatch.setattr(ris, "index_has_data", lambda: True)
    monkeypatch.setattr(ris, "_touch_heartbeat", lambda: heartbeats.append(1))
    monkeypatch.setattr(ris.time, "sleep", lambda s: (_ for _ in ()).throw(_StopLoop))

    with pytest.raises(_StopLoop):
        ris.watch()
    assert heartbeats == [1]
