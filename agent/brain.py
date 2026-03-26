"""
Gemini LLM brain — handles communication with the Gemini API.
Uses function calling so the LLM can invoke scraping tools.
"""

import os
import json
from typing import Optional

import google.generativeai as genai

from agent.prompts import SYSTEM_PROMPT


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
        model_name: str = "gemini-2.0-flash",
    ):
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY", "")
        if not self.api_key:
            raise ValueError(
                "Gemini API key not found. Set GEMINI_API_KEY env var "
                "or pass api_key= to GeminiBrain."
            )

        genai.configure(api_key=self.api_key)
        self.model_name = model_name
        self.model = None
        self.chat = None

    def start_session(self, tool_declarations: list[dict]) -> None:
        """
        Initialize a chat session with tool definitions.

        Args:
            tool_declarations: list of function declaration dicts
                               (see agent/tools.py for format)
        """
        self.model = genai.GenerativeModel(
            model_name=self.model_name,
            system_instruction=SYSTEM_PROMPT,
            tools=[{"function_declarations": tool_declarations}],
        )
        self.chat = self.model.start_chat()
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
            result: the result to send back (will be JSON-serialized if dict)

        Returns:
            Same format as send() — may contain more function calls or text.
        """
        if isinstance(result, dict):
            response_data = result
        else:
            response_data = {"result": str(result)}

        response = self.chat.send_message(
            genai.protos.Content(
                parts=[
                    genai.protos.Part(
                        function_response=genai.protos.FunctionResponse(
                            name=function_name,
                            response=response_data,
                        )
                    )
                ]
            )
        )
        return self._parse_response(response)

    def _parse_response(self, response) -> dict:
        """Extract text and function calls from a Gemini response."""
        parsed = {"text": "", "function_calls": []}

        try:
            parts = response.candidates[0].content.parts
        except (IndexError, AttributeError):
            return parsed

        for part in parts:
            if hasattr(part, "function_call") and part.function_call.name:
                parsed["function_calls"].append({
                    "name": part.function_call.name,
                    "args": dict(part.function_call.args),
                })
            if hasattr(part, "text") and part.text:
                parsed["text"] += part.text

        return parsed
