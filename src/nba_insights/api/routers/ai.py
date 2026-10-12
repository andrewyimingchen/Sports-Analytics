"""Natural-language league Q&A over one structured tool."""

from __future__ import annotations

import json
import logging
import os

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from nba_insights.analysis import COLUMN_GLOSSARY, query_players
from nba_insights.api import schemas
from nba_insights.api.deps import Client
from nba_insights.api.schemas import errors
from nba_insights.api.security import protect_ai
from nba_insights.config import current_season
from nba_insights.serve import league_with_ratings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["ai"])


class AskBody(BaseModel):
    question: str = Field(min_length=3, max_length=500)


@router.post(
    "/ask",
    dependencies=[Depends(protect_ai)],
    response_model=schemas.Answer,
    responses=errors(401, 403, 429, 502, 503),
)
def ask_league(body: AskBody, client: Client) -> dict:
    """Credential-safe natural-language Q&A over one structured league tool."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise HTTPException(
            503, "AI Q&A is optional: set ANTHROPIC_API_KEY or run `ant auth login`"
        )
    try:
        import anthropic
        from anthropic import beta_tool
    except ImportError as error:
        raise HTTPException(503, "AI Q&A requires `uv sync --extra ai`") from error

    league = league_with_ratings(client)

    @beta_tool
    def query_league(
        filters: dict | None = None,
        name_contains: str = "",
        teams: list | None = None,
        sort_by: str = "",
        ascending: bool = False,
        top_n: int = 10,
        columns: list | None = None,
    ) -> str:
        """Query current per-player stats; filters are inclusive minimums."""
        return json.dumps(
            query_players(
                league,
                filters=filters,
                name_contains=name_contains,
                teams=teams or None,
                sort_by=sort_by or None,
                ascending=ascending,
                top_n=top_n,
                columns=columns,
            )
        )

    glossary = "\n".join(f"- {column}: {meaning}" for column, meaning in COLUMN_GLOSSARY.items())
    system = (
        f"Answer NBA questions for {current_season()} using only query_league. "
        "Call the tool before stating any number. Percentages are fractions; present "
        "them as percentages. Keep the answer concise and mention active filters. "
        f"Available columns:\n{glossary}"
    )
    model = os.environ.get("NBA_ASK_MODEL", "claude-opus-4-8")
    try:
        runner = anthropic.Anthropic().beta.messages.tool_runner(
            model=model,
            max_tokens=2048,
            system=system,
            tools=[query_league],
            messages=[{"role": "user", "content": body.question}],
        )
        final = None
        for message in runner:
            final = message
        if final is None:
            raise RuntimeError("tool runner produced no message")
        answer = "".join(
            getattr(block, "text", "") for block in final.content if block.type == "text"
        )
    except anthropic.AuthenticationError as error:
        raise HTTPException(503, "Anthropic credential was rejected") from error
    except Exception as error:
        logger.warning("AI Q&A failed", exc_info=True)
        raise HTTPException(502, "AI answer failed") from error
    return {
        "answer": answer or "No answer was produced.",
        "model": model,
        "season": current_season(),
    }
