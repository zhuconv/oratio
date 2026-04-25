"""Smoke test: confirm Claude Agent SDK routes through the local `claude` CLI
and uses its auth (Pro/Max subscription), with no ANTHROPIC_API_KEY set."""

import asyncio
import os

from claude_agent_sdk import ClaudeAgentOptions, query


async def main() -> None:
    assert os.environ.get("ANTHROPIC_API_KEY") in (None, ""), (
        "ANTHROPIC_API_KEY is set; unset it to prove CLI auth works."
    )
    opts = ClaudeAgentOptions(
        model="claude-opus-4-6",
        system_prompt="You are a terse assistant. Answer in one short sentence.",
        allowed_tools=[],
        permission_mode="bypassPermissions",
    )
    collected: list[str] = []
    async for msg in query(prompt="Reply with exactly: CHORUS_OK", options=opts):
        collected.append(repr(msg)[:200])
    print("\n".join(collected[-6:]))


if __name__ == "__main__":
    asyncio.run(main())
