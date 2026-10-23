from datetime import timedelta
from typing import Any

from app.agent.loop import AgentDeps, Pricing, Retriever


def agent_deps(state: Any, retriever: Retriever | None = None) -> AgentDeps:
    """Everything a run needs, from the app's shared clients (app.state)."""
    settings = state.settings
    return AgentDeps(
        provider=state.provider,
        bus=state.bus,
        redis=state.redis,
        sessions=state.sessions,
        embedder=state.embedder,
        mailer=state.mailer,
        ticketing=state.ticketing,
        pricing=Pricing(settings.llm_price_in_per_mtok, settings.llm_price_out_per_mtok),
        retriever=retriever if settings.agent_prefetch else None,
        max_steps=settings.agent_max_steps,
        approval_ttl=timedelta(hours=settings.approval_ttl_hours),
        retrieval={
            "candidates": settings.retrieval_candidates,
            "top_k": settings.retrieval_top_k,
            "rrf_k": settings.retrieval_rrf_k,
        },
    )
