# Copyright (c) 2026 Beijing Volcano Engine Technology Co., Ltd.
# SPDX-License-Identifier: AGPL-3.0
"""Task tracking endpoints for OpenViking HTTP Server.

Provides observability for background operations (e.g. session commit
with ``wait=false``).  Callers receive a ``task_id`` and can poll these
endpoints to check completion, results, or errors.
"""

from typing import Optional

from fastapi import APIRouter, Body, Depends, Query
from pydantic import BaseModel, ConfigDict

from openviking.server.auth import get_request_context
from openviking.server.dependencies import get_service
from openviking.server.identity import RequestContext, Role
from openviking.server.models import Response
from openviking.service.task_store import SYSTEM_TASK_ACCOUNT_ID, SYSTEM_TASK_USER_ID
from openviking.service.task_tracker import classify_task_error, get_task_tracker
from openviking_cli.exceptions import (
    FailedPreconditionError,
    OpenVikingError,
    PermissionDeniedError,
)

router = APIRouter(prefix="/api/v1", tags=["tasks"])


class RetryTaskRequest(BaseModel):
    """Explicit acknowledgement for failures that require a repaired prerequisite."""

    model_config = ConfigDict(extra="forbid")

    acknowledge_change: bool = False
    restart_operation: bool = False


MAX_LINKED_RETRY_ATTEMPTS = 3


@router.get("/tasks/{task_id}")
async def get_task(
    task_id: str,
    _ctx: RequestContext = Depends(get_request_context),
):
    """Get the status of a single background task."""
    tracker = get_task_tracker()
    if _ctx.role == Role.ROOT:
        task = await tracker.get(task_id)
        if task is None:
            task = await tracker.get(
                task_id,
                account_id=SYSTEM_TASK_ACCOUNT_ID,
                user_id=SYSTEM_TASK_USER_ID,
            )
    else:
        task = await tracker.get(
            task_id,
            account_id=_ctx.account_id,
            user_id=_ctx.user.user_id,
        )
    if not task:
        raise OpenVikingError(
            "Task not found or expired",
            code="NOT_FOUND",
            details={"resource": task_id, "type": "task"},
        )
    return Response(status="ok", result=task.to_dict())


@router.post("/tasks/{task_id}/cancel")
async def cancel_task(
    task_id: str,
    _ctx: RequestContext = Depends(get_request_context),
):
    """Request cooperative cancellation of a background task."""
    if _ctx.role == Role.ROOT:
        raise PermissionDeniedError("ROOT may not cancel tasks")
    tracker = get_task_tracker()
    try:
        task = await tracker.cancel(
            task_id,
            account_id=_ctx.account_id,
            user_id=_ctx.user.user_id,
        )
    except ValueError as exc:
        raise FailedPreconditionError(str(exc)) from exc
    if task is None:
        raise OpenVikingError(
            "Task not found or expired",
            code="NOT_FOUND",
            details={"resource": task_id, "type": "task"},
        )
    return Response(status="ok", result=task.to_dict())


@router.post("/tasks/{task_id}/retry")
async def retry_task(
    task_id: str,
    body: RetryTaskRequest = Body(default_factory=RetryTaskRequest),
    _ctx: RequestContext = Depends(get_request_context),
):
    """Retry a failed task and return the task that now owns the work."""
    tracker = get_task_tracker()
    if _ctx.role == Role.ROOT:
        task = await tracker.get(task_id)
        if task is None:
            task = await tracker.get(
                task_id,
                account_id=SYSTEM_TASK_ACCOUNT_ID,
                user_id=SYSTEM_TASK_USER_ID,
            )
    else:
        task = await tracker.get(task_id, account_id=_ctx.account_id, user_id=_ctx.user.user_id)
    if task is None:
        raise OpenVikingError(
            "Task not found or expired",
            code="NOT_FOUND",
            details={"resource": task_id, "type": "task"},
        )
    if task.status.value == "completed":
        return Response(
            status="ok",
            result={
                "disposition": "operation_resolved",
                "operation_id": task.operation_id or task.task_id,
                "previous_task_id": task.task_id,
                "task_id": task.task_id,
                "attempt_number": task.attempt_number,
            },
        )
    if task.status.value != "failed":
        raise FailedPreconditionError("Only failed tasks can be retried")
    if not task.resource_id:
        raise FailedPreconditionError("Task has no retryable resource")

    resolved = await tracker.find_completed_operation(
        task.task_type,
        task.resource_id,
        task.operation_id or task.task_id,
        account_id=task.account_id or _ctx.account_id,
        user_id=task.user_id or _ctx.user.user_id,
    )
    if resolved is not None:
        await tracker.resolve_failed(
            task.task_id,
            resolved.result or {},
            account_id=task.account_id or _ctx.account_id,
            user_id=task.user_id or _ctx.user.user_id,
        )
        return Response(
            status="ok",
            result={
                "disposition": "operation_resolved",
                "operation_id": task.operation_id or task.task_id,
                "previous_task_id": task.task_id,
                "task_id": resolved.task_id,
                "attempt_number": resolved.attempt_number,
            },
        )

    service = get_service()
    if task.task_type == "session_commit":
        retry_state = await service.sessions.inspect_failed_commit(
            task.resource_id,
            task.task_id,
            _ctx,
            archive_uri=(task.meta or {}).get("archive_uri"),
            failed_task_created_at=task.created_at,
        )
        if retry_state.get("state") == "completed":
            await tracker.resolve_failed(
                task.task_id,
                {
                    "archive_uri": retry_state.get("archive_uri"),
                    "reason": "archive_complete",
                },
                account_id=task.account_id or _ctx.account_id,
                user_id=task.user_id or _ctx.user.user_id,
            )
            return Response(
                status="ok",
                result={
                    "disposition": "operation_resolved",
                    "operation_id": task.operation_id or task.task_id,
                    "previous_task_id": task.task_id,
                    "task_id": task.task_id,
                    "resolution": "archive_complete",
                    "archive_uri": retry_state.get("archive_uri"),
                },
            )

    # Historical records predate structured error information. Classify them at
    # the retry boundary too, so an old credential or media configuration error
    # cannot be replayed into an endless stream of new failures.
    error_info = task.error_info or classify_task_error(task.error or "")
    retryability = error_info.get("retryability", "manual")
    if retryability == "requires_change" and not body.acknowledge_change:
        return Response(
            status="ok",
            result={
                "disposition": "blocked",
                "operation_id": task.operation_id,
                "previous_task_id": task.task_id,
                "error": error_info,
            },
        )

    if task.attempt_number >= MAX_LINKED_RETRY_ATTEMPTS and not body.restart_operation:
        return Response(
            status="ok",
            result={
                "disposition": "retry_limit_reached",
                "operation_id": task.operation_id,
                "previous_task_id": task.task_id,
                "attempt_number": task.attempt_number,
                "max_attempts": MAX_LINKED_RETRY_ATTEMPTS,
                "action": "Fix the prerequisite, then explicitly start a new operation.",
            },
        )

    active = await tracker.find_active(
        task.task_type,
        task.resource_id,
        account_id=task.account_id or _ctx.account_id,
        user_id=task.user_id or _ctx.user.user_id,
    )
    if active is not None:
        return Response(
            status="ok",
            result={
                "disposition": "already_running",
                "operation_id": active.operation_id,
                "previous_task_id": task.task_id,
                "task_id": active.task_id,
                "attempt_number": active.attempt_number,
            },
        )

    if task.task_type == "session_commit":
        result = await service.sessions.retry_failed_commit(
            task.resource_id,
            task.task_id,
            _ctx,
            archive_uri=(task.meta or {}).get("archive_uri"),
            failed_task_created_at=task.created_at,
        )
    elif task.task_type in {"add_resource", "admin_reindex", "snapshot_restore_reindex"}:
        result = await service.reindex(
            uri=task.resource_id,
            mode="vectors_only",
            wait=False,
            ctx=_ctx,
        )
    else:
        raise FailedPreconditionError(
            f"Task type '{task.task_type}' does not have a safe server-side retry recipe"
        )

    if isinstance(result, dict) and result.get("reason") == "archive_complete":
        await tracker.resolve_failed(
            task.task_id,
            result,
            account_id=task.account_id or _ctx.account_id,
            user_id=task.user_id or _ctx.user.user_id,
        )
        return Response(
            status="ok",
            result={
                "disposition": "operation_resolved",
                "operation_id": task.operation_id or task.task_id,
                "previous_task_id": task.task_id,
                "task_id": task.task_id,
                "resolution": "archive_complete",
                "archive_uri": result.get("archive_uri"),
            },
        )

    new_task_id = result.get("task_id") if isinstance(result, dict) else None
    if not new_task_id:
        return Response(
            status="ok",
            result={
                "disposition": "no_action",
                "operation_id": task.operation_id,
                "previous_task_id": task.task_id,
                "result": result,
            },
        )
    linked = None
    if not body.restart_operation:
        linked = await tracker.link_retry(
            str(new_task_id),
            parent_task_id=task.task_id,
            account_id=task.account_id or _ctx.account_id,
            user_id=task.user_id or _ctx.user.user_id,
        )
    return Response(
        status="ok",
        result={
            "disposition": "accepted",
            "operation_id": (
                linked.operation_id
                if linked
                else (str(new_task_id) if body.restart_operation else task.operation_id)
            ),
            "previous_task_id": task.task_id,
            "task_id": str(new_task_id),
            "attempt_number": linked.attempt_number if linked else 1,
            "status_url": f"/api/v1/tasks/{new_task_id}",
        },
    )


@router.get("/tasks")
async def list_tasks(
    task_type: Optional[str] = Query(None, description="Filter by task type (e.g. session_commit)"),
    status: Optional[str] = Query(
        None,
        description="Filter by status (pending/running/cancelling/completed/failed/cancelled)",
    ),
    resource_id: Optional[str] = Query(None, description="Filter by resource ID (e.g. session_id)"),
    limit: int = Query(50, le=200, description="Max results"),
    _ctx: RequestContext = Depends(get_request_context),
):
    """List background tasks with optional filters."""
    tracker = get_task_tracker()
    if _ctx.role == Role.ROOT:
        system_tasks = await tracker.list_tasks(
            task_type=task_type,
            status=status,
            resource_id=resource_id,
            limit=limit,
            account_id=SYSTEM_TASK_ACCOUNT_ID,
            user_id=SYSTEM_TASK_USER_ID,
        )
        cached_tasks = await tracker.list_tasks(
            task_type=task_type,
            status=status,
            resource_id=resource_id,
            limit=limit,
        )
        tasks_by_id = {task.task_id: task for task in cached_tasks}
        tasks_by_id.update({task.task_id: task for task in system_tasks})
        tasks = sorted(tasks_by_id.values(), key=lambda task: task.created_at, reverse=True)[:limit]
    else:
        tasks = await tracker.list_tasks(
            task_type=task_type,
            status=status,
            resource_id=resource_id,
            limit=limit,
            account_id=_ctx.account_id,
            user_id=_ctx.user.user_id,
        )
    return Response(status="ok", result=[t.to_dict() for t in tasks])
