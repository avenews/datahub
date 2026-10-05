"""Claude tool-use loop wired to a DataHub MCP session.

Design constraints enforced here (see project brief):
- Answer only from tool results; never invent datasets/owners/lineage.
- Explicitly note when something may be hidden by the asker's permissions.
- Cap the number of tool-use rounds and truncate large tool outputs.
- Output must use Slack mrkdwn, not standard Markdown.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

SYSTEM_PROMPT_TEMPLATE = """You are the Avenews Data Buddy, the data-catalog assistant for \
Avenews, speaking inside Slack. Your tone is friendly, upbeat and a little playful, but \
professional and corporate-appropriate: brief warm openers are fine, an occasional relevant \
emoji is fine, jokes and slang are not. Refer to the catalog as "the Avenews catalog" and to \
the people you talk to as colleagues. Start answers with the point, not filler. When useful, \
end with one short suggested follow-up question.

Rules you must follow:
- Only answer using information returned by the DataHub tools available to you. \
Never invent, guess, or assume datasets, owners, tags, lineage, or any other \
metadata that the tools did not actually return.
- If a search or lookup returns nothing, or looks incomplete, say so plainly. \
Also say plainly that the result may be limited by the asker's own DataHub \
permissions -- they only see what they're allowed to see, and so do you.
- Use one or more tool calls whenever they would help answer the question. \
Do not answer from general knowledge about "typical" data catalogs.
- Format your final answer using Slack mrkdwn, NOT standard Markdown:
  - Bold: *text* (single asterisks, not **text**)
  - Italic: _text_
  - Inline code: `text`
  - Links: <https://example.com|link text>
  - Bulleted lists: use "- " on its own line
- When you reference a DataHub entity the user could open, include a link built as \
  <{ui_url}/<entity-type>/<urn>|<name>> using the entity's type and URN from the tool \
  results (e.g. <{ui_url}/dataset/urn:li:dataset:(...)|orders_daily>). Do not invent URLs.
- Be concise. This is a chat answer, not a report.
"""


@dataclass
class AnswerResult:
    text: str
    tool_rounds_used: int
    hit_round_cap: bool


class McpSessionProtocol(Protocol):
    async def list_tools_as_claude_schema(self) -> list[dict[str, Any]]: ...

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> str: ...


class McpToolErrorProtocol(Protocol):
    pass


def _truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + f"\n...[truncated, {len(text) - max_chars} more characters omitted]"


def _extract_text_blocks(content_blocks: list[Any]) -> str:
    parts = []
    for block in content_blocks:
        block_type = getattr(block, "type", None) or (block.get("type") if isinstance(block, dict) else None)
        if block_type == "text":
            parts.append(getattr(block, "text", None) or block.get("text", ""))
    return "\n".join(parts).strip()


@dataclass
class ClaudeDataHubAnswerer:
    anthropic_client: Any
    model: str
    datahub_ui_url: str
    max_tool_rounds: int = 6
    tool_result_max_chars: int = 4000
    max_tokens: int = 1500
    mcp_tool_error_type: type = field(default=Exception)

    async def answer(
        self,
        mcp_session: McpSessionProtocol,
        history: list[dict[str, Any]],
        question: str,
    ) -> AnswerResult:
        tools = await mcp_session.list_tools_as_claude_schema()
        anthropic_tools = [
            {
                "name": tool["name"],
                "description": tool["description"],
                "input_schema": tool["input_schema"],
            }
            for tool in tools
        ]
        system_prompt = SYSTEM_PROMPT_TEMPLATE.format(ui_url=self.datahub_ui_url)

        messages: list[dict[str, Any]] = [*history, {"role": "user", "content": question}]

        rounds_used = 0
        for _ in range(self.max_tool_rounds):
            response = await self.anthropic_client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=system_prompt,
                tools=anthropic_tools,
                messages=messages,
            )

            if response.stop_reason != "tool_use":
                return AnswerResult(
                    text=_extract_text_blocks(response.content),
                    tool_rounds_used=rounds_used,
                    hit_round_cap=False,
                )

            rounds_used += 1
            messages.append({"role": "assistant", "content": response.content})

            tool_results = []
            for block in response.content:
                if getattr(block, "type", None) != "tool_use":
                    continue
                try:
                    result_text = await mcp_session.call_tool(block.name, block.input)
                except self.mcp_tool_error_type as exc:
                    result_text = f"Tool call failed: {exc}"
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": _truncate(result_text, self.tool_result_max_chars),
                    }
                )
            messages.append({"role": "user", "content": tool_results})

        # Round cap hit: force one final answer-only turn, no more tool calls.
        final_response = await self.anthropic_client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system_prompt
            + "\nYou have used all available tool calls. Answer using only what you "
            "already found, and clearly say if you were not able to fully answer.",
            tools=anthropic_tools,
            tool_choice={"type": "none"},
            messages=messages,
        )
        return AnswerResult(
            text=_extract_text_blocks(final_response.content),
            tool_rounds_used=rounds_used,
            hit_round_cap=True,
        )
