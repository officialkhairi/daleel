"""Human approval of side-effect tool calls. Deciding the last pending approval of a run resumes
it on the run's event stream: follow GET /api/runs/{run_id}/events from `resume_from`."""

import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field, StringConstraints, ValidationError
from sqlalchemy import func, select

from app.agent import audit
from app.agent.factory import agent_deps
from app.agent.loop import resume_run
from app.agent.schemas import ApprovalOut, load_approvals
from app.agent.tools import TOOLS
from app.api.chats import any_role
from app.auth.deps import require
from app.auth.principal import Principal
from app.chat import repo
from app.db.models import Approval, Run
from app.db.session import tenant_session
from app.documents.progress import ApprovalNotice, publish
from app.errors import AppError, NotFound

router = APIRouter(prefix="/api/approvals", tags=["approvals"])
approver_role = require("approver", "admin")


class AlreadyDecided(AppError):
    status_code = 409
    code = "already_decided"


class InvalidArgs(AppError):
    status_code = 422
    code = "validation_error"


class Decision(BaseModel):
    decision: Literal["approve", "edit", "reject"]
    args: dict[str, Any] | None = Field(
        default=None, description="Edited arguments (for 'edit'); validated like the model's."
    )
    reason: Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)] | None = None


class DecisionOut(BaseModel):
    approval: ApprovalOut
    resumed: bool = Field(description="True when this was the run's last pending approval.")
    run_id: uuid.UUID
    resume_from: str | None = Field(
        description="Follow the run's events after this id to see it continue."
    )


@router.get("")
async def list_(
    request: Request,
    status: Annotated[
        Literal["pending", "approved", "rejected", "expired"] | None, Query()
    ] = "pending",
    principal: Principal = Depends(approver_role),
) -> list[ApprovalOut]:
    """The approval inbox: everything in the tenant awaiting (or past) a decision."""
    where = [Approval.status == status] if status else []
    async with tenant_session(request.app.state.sessions, principal.tenant_id) as session:
        return await load_approvals(session, *where)


@router.get("/{approval_id}")
async def get(
    approval_id: uuid.UUID, request: Request, principal: Principal = Depends(any_role)
) -> ApprovalOut:
    """Approvers see any approval in the tenant; others only those they asked for."""
    async with tenant_session(request.app.state.sessions, principal.tenant_id) as session:
        user_id = await repo.ensure_user_id(session, principal)
        found = await load_approvals(session, Approval.id == approval_id)
    if not found or not (
        principal.roles & {"approver", "admin"} or found[0].requested_by == user_id
    ):
        raise NotFound("Approval not found.")
    return found[0]


@router.post("/{approval_id}")
async def decide(
    approval_id: uuid.UUID,
    body: Decision,
    request: Request,
    principal: Principal = Depends(approver_role),
) -> DecisionOut:
    state = request.app.state
    async with tenant_session(state.sessions, principal.tenant_id) as session:
        user_id = await repo.ensure_user_id(session, principal)
        approval = await session.scalar(
            select(Approval).where(Approval.id == approval_id).with_for_update()
        )
        if approval is None:
            raise NotFound("Approval not found.")
        db_now = await session.scalar(select(func.now()))
        if approval.status == "pending" and db_now is not None and db_now > approval.expires_at:
            approval.status = "expired"
            approval.reason = "Expired before a decision."
        if approval.status != "pending":
            raise AlreadyDecided(f"This action was already {approval.status}.")

        tool = TOOLS[approval.tool]
        action = "approval.rejected"
        if body.decision == "reject":
            approval.status = "rejected"
            approval.reason = body.reason
        else:
            if body.args is not None and body.args != approval.args:
                try:
                    approval.edited_args = tool.parse(body.args).model_dump(mode="json")
                except ValidationError as exc:
                    problems = "; ".join(
                        f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()
                    )
                    raise InvalidArgs(f"Invalid arguments: {problems}") from exc
            elif body.decision == "edit":
                raise InvalidArgs("Editing needs the changed arguments.")
            approval.status = "approved"
            approval.reason = body.reason
            action = "approval.edited" if approval.edited_args is not None else "approval.approved"
        approval.decided_by = user_id
        approval.decided_at = func.now()
        await audit.record(
            session,
            tenant_id=principal.tenant_id,
            actor_id=user_id,
            actor=principal.username,
            action=action,
            target_type="approval",
            target_id=approval.id,
            details={
                "tool": approval.tool,
                "args": approval.args,
                "edited_args": approval.edited_args,
                "reason": approval.reason,
            },
        )
        await session.flush()

        run = await session.scalar(select(Run).where(Run.id == approval.run_id).with_for_update())
        still_pending = await session.scalar(
            select(func.count())
            .select_from(Approval)
            .where(Approval.run_id == approval.run_id, Approval.status == "pending")
        )
        resume = run is not None and run.status == "awaiting_approval" and not still_pending
        if resume and run is not None:
            run.status = "running"
        run_id, chat_id, requested_by = approval.run_id, approval.chat_id, approval.requested_by
        status = approval.status

    out = await _reload(state, principal, approval_id)
    await publish(
        state.redis,
        principal.tenant_id,
        ApprovalNotice(
            type="approval.decided",
            approval_id=approval_id,
            run_id=run_id,
            chat_id=chat_id,
            tool=out.tool,
            status=status,
            requested_by=requested_by,
        ),
    )
    resume_from = await state.bus.last_event_id(run_id)
    if resume:
        state.tasks.spawn(
            resume_run(run_id, principal.tenant_id, agent_deps(state)), name=f"resume-{run_id}"
        )
    return DecisionOut(approval=out, resumed=resume, run_id=run_id, resume_from=resume_from)


async def _reload(state: Any, principal: Principal, approval_id: uuid.UUID) -> ApprovalOut:
    async with tenant_session(state.sessions, principal.tenant_id) as session:
        return (await load_approvals(session, Approval.id == approval_id))[0]
