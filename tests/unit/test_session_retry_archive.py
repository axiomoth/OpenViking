# Copyright (c) 2026 Beijing Volcano Engine Technology Co., Ltd.
# SPDX-License-Identifier: AGPL-3.0
"""Unit tests for legacy session commit archive resolution."""

import json
from types import SimpleNamespace

import pytest

from openviking.session.session import Session

SESSION_URI = "viking://user/alice/sessions/session-1"
ARCHIVE_URI = f"{SESSION_URI}/history/archive_003"
FAILED_TASK_CREATED_AT = 1786994253.298716


class _AsyncAgfs:
    async def pathlock_acquire_tree(self, _path, timeout_secs):
        assert timeout_secs > 0
        return "lease"

    async def pathlock_release(self, lease):
        assert lease == "lease"


class _VikingFS:
    def __init__(self):
        self._async_agfs = _AsyncAgfs()

    async def glob(self, pattern, *, uri, ctx):
        assert pattern == "archive_*/messages.jsonl"
        assert uri == f"{SESSION_URI}/history"
        assert ctx is not None
        return {"matches": [f"{ARCHIVE_URI}/messages.jsonl"]}

    async def read_file(self, uri, *, ctx):
        assert uri == f"{ARCHIVE_URI}/.meta.json"
        assert ctx is not None
        return json.dumps(
            {
                "phase1": {
                    "created_at": "2026-08-17T19:17:33.276Z",
                    "queue_message": {"task_id": "offline-recovery-task"},
                }
            }
        )

    async def exists(self, uri, *, ctx):
        assert ctx is not None
        return uri == f"{ARCHIVE_URI}/.done"

    def _uri_to_path(self, uri, *, ctx):
        assert uri == SESSION_URI
        assert ctx is not None
        return "/session-1"


def _session() -> Session:
    session = Session.__new__(Session)
    session._viking_fs = _VikingFS()
    session._session_uri = SESSION_URI
    session.session_id = "session-1"
    session.ctx = SimpleNamespace()
    return session


@pytest.mark.asyncio
async def test_legacy_archive_is_matched_by_creation_time_after_queue_id_replacement():
    state = await _session().inspect_failed_commit(
        "legacy-failed-task",
        failed_task_created_at=FAILED_TASK_CREATED_AT,
    )

    assert state == {"state": "completed", "archive_uri": ARCHIVE_URI}


@pytest.mark.asyncio
async def test_retry_returns_resolved_when_legacy_archive_is_already_complete():
    result = await _session().retry_failed_commit(
        "legacy-failed-task",
        failed_task_created_at=FAILED_TASK_CREATED_AT,
    )

    assert result == {
        "session_id": "session-1",
        "status": "completed",
        "task_id": None,
        "archive_uri": ARCHIVE_URI,
        "reason": "archive_complete",
    }
