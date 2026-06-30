#!/usr/bin/env python3
"""Personal Finance Agent — orchestrates budget, goal, investment, and debt subagents."""

import json
import os
import sys
from typing import Any, Dict

from openai import OpenAI
from dotenv import load_dotenv
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt
from rich.rule import Rule
from rich.text import Text

from config import has_openai_api_key, normalize_openai_api_key, openai_model
import observability

load_dotenv()
normalize_openai_api_key()

console = Console()

ORCHESTRATOR_SYSTEM = """You are a personal finance orchestrator. Your role is to understand what the user needs and delegate to the right specialist agent(s).

You have four specialist subagents available via tools:
1. **Budget Agent** — tracks income/expenses, sets budget limits, analyzes spending
2. **Goal Agent** — creates financial goals, tracks progress, calculates savings plans
3. **Investment Agent** — risk profiling, portfolio recommendations, compound growth projections
4. **Debt Agent** — tracks debts, calculates snowball/avalanche payoff plans, compares strategies

Rules:
- ALWAYS delegate to a subagent via tool call — never answer finance questions yourself without a subagent
- If the request touches multiple domains, call all relevant subagents (you can call multiple tools)
- Pass the user's exact words plus any useful context to the subagent task parameter
- After receiving subagent responses, synthesize them into one coherent reply for the user
- Keep your synthesis concise — the subagents provide the details
- If the user's intent is unclear, ask ONE clarifying question before delegating

Respond in a warm, encouraging tone. Help users feel in control of their finances."""

ORCHESTRATOR_TOOLS = [
    {"type": "function", "function": {
        "name": "consult_budget_agent",
        "description": (
            "Delegate to the budget tracking specialist. Use for: adding transactions (income/expenses), "
            "viewing spending summaries, setting monthly budget limits, analyzing spending by category."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "The budget task or question, including all relevant numbers and context from the user",
                }
            },
            "required": ["task"],
        },
    }},
    {"type": "function", "function": {
        "name": "consult_goal_agent",
        "description": (
            "Delegate to the financial goal planning specialist. Use for: creating savings goals, "
            "tracking progress toward goals, calculating required monthly savings, updating goal amounts."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "The goal planning task, including target amounts, deadlines, and current savings",
                }
            },
            "required": ["task"],
        },
    }},
    {"type": "function", "function": {
        "name": "consult_investment_agent",
        "description": (
            "Delegate to the investment guide specialist. Use for: setting a risk profile, getting portfolio "
            "allocation recommendations, projecting compound growth, comparing investment scenarios, "
            "explaining investment types (ETFs, index funds, Roth IRA, 401k, etc.)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "The investment question or task, including risk tolerance, amounts, and time horizon",
                }
            },
            "required": ["task"],
        },
    }},
    {"type": "function", "function": {
        "name": "consult_debt_agent",
        "description": (
            "Delegate to the debt payoff specialist. Use for: adding debts to track, viewing debt summary, "
            "calculating snowball or avalanche payoff plans, comparing payoff strategies, updating balances."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "The debt management task, including balances, interest rates, and available extra payments",
                }
            },
            "required": ["task"],
        },
    }},
]


AGENT_MAP = None  # lazy import

ROUTER_SYSTEM = """You are a finance request router. Analyze the user's message and output ONLY valid JSON.

Available agents: "budget", "goal", "investment", "debt"

- budget: add/view income or expenses, set spending limits, spending analysis
- goal: savings goals, progress tracking, savings plans, deadlines
- investment: risk profiles, portfolio recommendations, compound growth, ETFs, Roth IRA, 401k
- debt: track debts, payoff plans, snowball/avalanche strategy, interest calculations

Output format:
{"agents": ["budget"], "task": "rephrase the request for the agent(s)"}

Include all relevant agents. The "task" should include all key numbers and context from the user's message."""


def _get_agent_map():
    global AGENT_MAP
    if AGENT_MAP is None:
        from agents import budget_agent, debt_agent, goal_agent, investment_agent
        AGENT_MAP = {
            "budget": (budget_agent.run, "Budget"),
            "goal": (goal_agent.run, "Goal"),
            "investment": (investment_agent.run, "Investment"),
            "debt": (debt_agent.run, "Debt"),
        }
    return AGENT_MAP


def run_orchestrator(user_message: str, conversation_history: list) -> str:
    client = OpenAI()
    conversation_history.append({"role": "user", "content": user_message})

    # Step 1: Route — use JSON mode (no tool calls, no format issues)
    router_response = client.chat.completions.create(
        model=openai_model(),
        messages=[
            {"role": "system", "content": ROUTER_SYSTEM},
            {"role": "user", "content": user_message},
        ],
        response_format={"type": "json_object"},
        max_tokens=300,
        temperature=0,
    )
    routing = json.loads(router_response.choices[0].message.content)
    agents_to_call = routing.get("agents", ["budget"])
    task = routing.get("task", user_message)

    # Step 2: Call each subagent
    agent_map = _get_agent_map()
    results: dict[str, str] = {}
    for agent_key in agents_to_call:
        if agent_key not in agent_map:
            continue
        fn, label = agent_map[agent_key]
        with console.status(f"[dim]Consulting {label} Agent...[/dim]", spinner="dots"):
            results[label] = fn(task)

    if not results:
        return "I'm not sure how to help with that. Try asking about budgeting, goals, investing, or debt."

    # Step 3: If one agent, return directly; otherwise synthesize
    if len(results) == 1:
        reply = next(iter(results.values()))
        conversation_history.append({"role": "assistant", "content": reply})
        return reply

    combined = "\n\n".join(f"**{label} Agent:**\n{resp}" for label, resp in results.items())
    synth_response = client.chat.completions.create(
        model=openai_model(),
        messages=[
            {"role": "system", "content": ORCHESTRATOR_SYSTEM},
            {"role": "user", "content": user_message},
            {"role": "assistant", "content": f"I've gathered input from multiple specialists:\n\n{combined}"},
            {"role": "user", "content": "Please synthesize this into one clear, helpful response."},
        ],
        max_tokens=2048,
    )
    reply = synth_response.choices[0].message.content or combined
    conversation_history.append({"role": "assistant", "content": reply})
    return reply


def print_welcome():
    console.print()
    console.print(Panel(
        Text.assemble(
            ("Personal Finance Agent\n", "bold cyan"),
            ("Your AI-powered financial planning companion\n\n", "dim"),
            ("Specialists on call:\n", "bold white"),
            ("  Budget Tracker  ", "green"), ("• ", "dim"),
            ("Goal Planner  ", "yellow"), ("• ", "dim"),
            ("Investment Guide  ", "blue"), ("• ", "dim"),
            ("Debt Eliminator\n\n", "red"),
            ("Type ", "dim"), ("help ", "bold"), ("for example prompts, or ", "dim"),
            ("quit ", "bold"), ("to exit.", "dim"),
        ),
        border_style="cyan",
        padding=(1, 2),
    ))
    console.print()


HELP_TEXT = """
## Example prompts to get started

**Budget:**
- "I spent $120 on groceries today"
- "Add my salary of $5,500 for June"
- "Set a $300/month limit for dining out"
- "Show me my spending summary for this month"

**Goals:**
- "I want to save $10,000 for an emergency fund by December 2026"
- "I'm saving for a house down payment of $60,000 by 2028, I have $8,000 saved"
- "Show me all my financial goals"

**Investing:**
- "I'm 28, moderate risk tolerance, investing for 30 years, can invest $500/month"
- "If I invest $200/month for 20 years at 7% return, what will I have?"
- "Compare investment scenarios for $300/month over 15 years"
- "Explain what a Roth IRA is and should I open one?"

**Debt:**
- "I have a Chase credit card with $4,500 balance, 24% APR, $90 minimum"
- "Add my student loan: $18,000 balance, 5.5% interest, $200/month minimum"
- "Show me a snowball vs avalanche comparison with $200 extra per month"
"""


def main():
    observability.configure_logging()
    if not has_openai_api_key():
        console.print("[bold red]Error:[/bold red] OPENAI_API_KEY not set.")
        console.print("Copy [bold].env.example[/bold] to [bold].env[/bold] and add your OpenAI API key.")
        sys.exit(1)

    print_welcome()

    conversation_history = []

    while True:
        try:
            user_input = Prompt.ask("[bold cyan]You[/bold cyan]").strip()
        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]Goodbye! Stay on track with your finances.[/dim]")
            break

        if not user_input:
            continue

        if user_input.lower() in ("quit", "exit", "q", "bye"):
            console.print("[dim]Goodbye! Stay on track with your finances.[/dim]")
            break

        if user_input.lower() in ("help", "h", "?"):
            console.print(Markdown(HELP_TEXT))
            continue

        console.print()
        try:
            reply = run_orchestrator(user_input, conversation_history)
            console.print(Rule(style="dim"))
            console.print(Markdown(reply))
            console.print(Rule(style="dim"))
        except Exception as e:
            console.print(f"[red]Error:[/red] {e}")
            raise

        console.print()


if __name__ == "__main__":
    main()
