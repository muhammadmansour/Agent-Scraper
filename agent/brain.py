"""
Gemini LLM brain — handles communication with the Gemini API.
Uses function calling so the LLM can invoke scraping tools.

Uses the new `google-genai` SDK (not the deprecated `google-generativeai`).
"""

import os
from typing import Optional

from google import genai
from google.genai import types

from agent.prompts import SYSTEM_PROMPT


def _resolve_api_key(explicit_key: Optional[str] = None) -> str:
    """
    Resolve the Gemini API key from multiple sources:
      1. Explicitly passed key
      2. GEMINI_API_KEY env var
      3. GOOGLE_API_KEY env var (common fallback)
    """
    key = (
        explicit_key
        or os.environ.get("GEMINI_API_KEY", "")
        or os.environ.get("GOOGLE_API_KEY", "")
    )
    if not key:
        raise ValueError(
            "Gemini API key not found. Tried:\n"
            "  1. --gemini-key CLI flag\n"
            "  2. GEMINI_API_KEY env var\n"
            "  3. GOOGLE_API_KEY env var\n"
            "\n"
            "Set it with:\n"
            "  Windows (PowerShell):  $env:GEMINI_API_KEY='your-key'\n"
            "  Windows (cmd):         set GEMINI_API_KEY=your-key\n"
            "  Linux/Mac:             export GEMINI_API_KEY='your-key'\n"
            "  Or pass:               python agent.py --agent --gemini-key your-key"
        )
    return key


class GeminiBrain:
    """
    Wraps the Gemini API with function calling support.

    Usage:
        brain = GeminiBrain(api_key="...")
        brain.start_session(tool_declarations)
        response = brain.send("Current state: ...")
        # response = {"text": "...", "function_calls": [{"name": "...", "args": {...}}]}
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model_name: str = "gemini-2.5-pro",
    ):
        self.api_key = _resolve_api_key(api_key)
        self.model_name = model_name
        self.client = genai.Client(api_key=self.api_key)
        self.chat = None

    def start_session(self, tool_declarations: list[dict]) -> None:
        """
        Initialize a chat session with tool definitions.

        Args:
            tool_declarations: list of function declaration dicts
                               (see agent/tools.py TOOL_DECLARATIONS)
        """
        # Build Tool objects from declaration dicts
        func_decls = []
        for decl in tool_declarations:
            func_decls.append(types.FunctionDeclaration(
                name=decl["name"],
                description=decl.get("description", ""),
                parameters=decl.get("parameters"),
            ))

        config = types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            tools=[types.Tool(function_declarations=func_decls)],
        )

        self.chat = self.client.chats.create(
            model=self.model_name,
            config=config,
        )
        print(f"  [brain] Gemini session started ({self.model_name})")

    def send(self, message: str) -> dict:
        """
        Send a message to Gemini and parse the response.

        Returns:
            {
                "text": "LLM's reasoning text",
                "function_calls": [{"name": "tool_name", "args": {...}}, ...]
            }
        """
        if self.chat is None:
            raise RuntimeError("Call start_session() before send()")

        response = self.chat.send_message(message)
        return self._parse_response(response)

    def send_tool_result(self, function_name: str, result: dict | str) -> dict:
        """
        Send the result of a tool execution back to Gemini.

        Args:
            function_name: name of the function that was called
            result: the result to send back

        Returns:
            Same format as send() — may contain more function calls or text.
        """
        if isinstance(result, str):
            response_data = {"result": result}
        else:
            response_data = result

        # Use Part.from_function_response to build the response part
        part = types.Part.from_function_response(
            name=function_name,
            response=response_data,
        )

        response = self.chat.send_message(part)
        return self._parse_response(response)

    def _parse_response(self, response) -> dict:
        """Extract text and function calls from a Gemini response."""
        parsed = {"text": "", "function_calls": []}

        try:
            parts = response.candidates[0].content.parts
        except (IndexError, AttributeError):
            return parsed

        for part in parts:
            if part.function_call and part.function_call.name:
                parsed["function_calls"].append({
                    "name": part.function_call.name,
                    "args": dict(part.function_call.args) if part.function_call.args else {},
                })
            if part.text:
                parsed["text"] += part.text

        return parsed
