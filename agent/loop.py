"""
Agent loop — the core observe → reason → act → learn cycle.

This is where the LLM-powered decision-making happens.
The loop runs until the agent calls finish() or hits max iterations.
"""

import json
from datetime import datetime, timezone

from agent.brain import GeminiBrain
from agent.tools import AgentTools, TOOL_DECLARATIONS
from agent.observer import Observer
from agent.memory import AgentMemory


MAX_TURNS = 100          # safety limit — prevent infinite loops
MAX_TOOL_CALLS = 500     # max total tool calls across all turns


class AgentLoop:
    """
    LLM-powered scraping agent.

    observe() → Gemini reasons → calls a tool → result fed back → repeat
    """

    def __init__(
        self,
        api_key: str | None = None,
        model_name: str = "gemini-2.0-flash",
        download_pdf: bool = True,
        max_workers: int = 3,
    ):
        self.brain = GeminiBrain(api_key=api_key, model_name=model_name)
        self.tools = AgentTools(download_pdf=download_pdf, max_workers=max_workers)
        self.observer = Observer()
        self.memory = AgentMemory()
        self.turn_count = 0
        self.tool_call_count = 0

    def run(self, goal: str = "") -> None:
        """
        Main agent loop.

        Args:
            goal: optional high-level goal from the user
                  (e.g., "scrape all NCAR documents")
        """
        print("\n" + "═" * 60)
        print("  🤖 AGENTIC SCRAPER — Starting")
        print("═" * 60)

        # Start LLM session with tool declarations
        self.brain.start_session(TOOL_DECLARATIONS)
        self.memory.log_session_start()

        # Initial observation
        memory_context = self.memory.get_context_for_llm()
        observation = self.observer.observe()

        initial_message = (
            f"Goal: {goal}\n\n" if goal else ""
        ) + (
            f"{memory_context}\n" if memory_context else ""
        ) + observation

        print("\n  [agent] Sending initial observation to Gemini...")
        response = self.brain.send(initial_message)

        while self.turn_count < MAX_TURNS and self.tool_call_count < MAX_TOOL_CALLS:
            self.turn_count += 1

            # Display LLM's reasoning
            if response.get("text"):
                print(f"\n  💭 Agent thinking: {response['text'][:300]}")

            # No function calls → LLM is done talking, send new observation
            if not response.get("function_calls"):
                if self.tools.finished:
                    break
                print("  [agent] No tool call — refreshing observation...")
                observation = self.observer.observe()
                response = self.brain.send(
                    "You didn't call a tool. Please decide on an action:\n\n" + observation
                )
                continue

            # Execute each function call
            last_result = None
            for fc in response["function_calls"]:
                tool_name = fc["name"]
                tool_args = fc["args"]
                self.tool_call_count += 1

                # Convert numeric args from float to int where needed
                for key, val in tool_args.items():
                    if isinstance(val, float) and val == int(val):
                        tool_args[key] = int(val)

                print(f"\n  🔧 Tool: {tool_name}({json.dumps(tool_args, ensure_ascii=False)})")

                # Execute
                result = self.tools.execute(tool_name, tool_args)
                last_result = result

                result_str = json.dumps(result, ensure_ascii=False, indent=2)
                print(f"  📊 Result: {result_str[:500]}")

                # Log decision
                reasoning = response.get("text", "")[:200]
                result_summary = result_str[:200]
                self.memory.log_decision(tool_name, tool_args, reasoning, result_summary)

                # Check for high failure rate → add pattern
                if tool_name == "scrape_pages" and isinstance(result, dict):
                    failures = result.get("failures", 0)
                    docs = result.get("documents_scraped", 1)
                    if docs > 0 and failures / docs > 0.3:
                        src = tool_args.get("source", "")
                        self.memory.add_pattern(
                            f"High failure rate ({failures}/{docs}) on pages {tool_args.get('start_page')}-{tool_args.get('end_page')}",
                            source=src,
                        )

                # Check if agent is done
                if self.tools.finished:
                    break

            if self.tools.finished:
                break

            # Send tool result back to Gemini with updated observation
            observation = self.observer.observe(
                extra_context=json.dumps(last_result, ensure_ascii=False, indent=2)
            )
            response = self.brain.send_tool_result(
                function_name=response["function_calls"][-1]["name"],
                result={"observation": observation},
            )

        # Session complete
        reason = self.tools.finish_reason or f"Max turns ({self.turn_count})"
        self.memory.log_session_end(reason)

        print("\n" + "═" * 60)
        print(f"  🤖 AGENT DONE — {reason}")
        print(f"     Turns: {self.turn_count} | Tool calls: {self.tool_call_count}")
        print("═" * 60 + "\n")
