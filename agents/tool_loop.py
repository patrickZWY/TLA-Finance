"""
JSON-mode agentic loop for OpenAI.
Uses response_format=json_object instead of model-native tool calls so the
local tool dispatcher stays provider-agnostic.
"""
import json
import logging
from typing import Any, Callable, Dict, List

from openai import OpenAI

from config import normalize_openai_api_key, openai_model
import observability

MODEL = openai_model()
MAX_STEPS = 8
logger = logging.getLogger(__name__)


def _tools_to_description(tools: List[Dict]) -> str:
    lines = []
    for t in tools:
        fn = t["function"]
        params = fn.get("parameters", {}).get("properties", {})
        required = fn.get("parameters", {}).get("required", [])
        param_desc = ", ".join(
            f"{k} ({'required' if k in required else 'optional'}): {v.get('description', v.get('type', ''))}"
            for k, v in params.items()
        )
        lines.append(f"  - {fn['name']}: {fn['description']}")
        if param_desc:
            lines.append(f"    Args: {param_desc}")
    return "\n".join(lines)


LOOP_SUFFIX = """

## Tool use instructions
You have tools available. Always call at least one tool before giving a final answer.
Output ONLY valid JSON each turn — no prose, no markdown.

To call a tool:
{{"action": "call_tool", "tool": "<tool_name>", "args": {{<arguments>}}}}

To give your final answer after you have the data you need:
{{"action": "answer", "text": "<your full helpful response in markdown>"}}

The downstream safety gate semantically extracts concrete money actions from your answer.
If you include a machine-readable action block, it must use this exact shape:
```finance-actions
{{"actions":[]}}
```

If you include the block and propose concrete executable money movement, trade, deposit,
withdrawal, transfer, buy, sell, or swap instructions, include each one in that JSON list:
{{"action":"buy|sell|swap|deposit|transfer|withdraw","amount":123,"from":"account","to":"account"}}

If your response is only educational, hypothetical, descriptive, or already recorded by an
internal bookkeeping tool, use an empty actions list when you include the block. Never put
comments inside the JSON block.

Available tools:
{tools_description}"""


def run(
    system_prompt: str,
    task: str,
    tools: List[Dict],
    handle_tool: Callable[[str, Dict[str, Any]], str],
) -> str:
    normalize_openai_api_key()
    client = OpenAI()
    tool_names = {t["function"]["name"] for t in tools}
    tools_description = _tools_to_description(tools)
    enhanced_system = system_prompt + LOOP_SUFFIX.format(tools_description=tools_description)

    messages = [
        {"role": "system", "content": enhanced_system},
        {"role": "user", "content": task},
    ]

    for step in range(1, MAX_STEPS + 1):
        with observability.operation(
            logger,
            "tool_loop.model_call",
            model=MODEL,
            step=step,
        ):
            response = client.chat.completions.create(
                model=MODEL,
                messages=messages,
                response_format={"type": "json_object"},
                max_tokens=2048,
                temperature=0.1,
            )
        raw = response.choices[0].message.content or "{}"

        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            observability.log_event(
                logger,
                "tool_loop.parse_failure",
                level=logging.WARNING,
                step=step,
                error_type=type(exc).__name__,
            )
            observability.log_event(
                logger,
                "tool_loop.outcome",
                outcome="parse_failure",
                steps=step,
            )
            return raw

        # Normalise: if model returned a list of actions, process them all
        actions = parsed if isinstance(parsed, list) else [parsed]

        tool_called = False
        final_answer = None

        for item in actions:
            if not isinstance(item, dict):
                continue
            action = item.get("action", "")

            if action == "answer":
                final_answer = item.get("text", raw)
                break

            if action == "call_tool":
                tool_name = item.get("tool", "")
                args = item.get("args") or {}
            elif action in tool_names:
                tool_name = action
                args = item.get("args") or item.get("arguments") or {}
            else:
                final_answer = item.get("text", raw)
                break

            with observability.operation(
                logger,
                "tool_loop.tool_call",
                step=step,
                tool_name=tool_name,
                args=observability.payload(args),
            ):
                tool_result = handle_tool(tool_name, args)
            messages.append({"role": "assistant", "content": json.dumps(item)})
            messages.append({"role": "user", "content": f"Tool result for {tool_name}:\n{tool_result}"})
            tool_called = True

        if final_answer is not None:
            observability.log_event(
                logger,
                "tool_loop.outcome",
                outcome="final",
                steps=step,
            )
            return final_answer
        if not tool_called:
            observability.log_event(
                logger,
                "tool_loop.outcome",
                outcome="no_tool_called",
                steps=step,
            )
            return raw

    observability.log_event(
        logger,
        "tool_loop.outcome",
        outcome="max_steps",
        steps=MAX_STEPS,
    )
    return "I was unable to complete the request within the allowed steps."
