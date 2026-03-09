"""DeepSeek LLM adapter for repository summarization.

Provides async interface to DeepSeek API via Nebius TokenFactory (OpenAI-compatible endpoint).
Supports structured output using Pydantic schemas for reliable, type-safe responses.
"""

import json
import os
from typing import Any, Optional

import httpx
import tiktoken
from pydantic import BaseModel

from .models import (
    RepositorySummary,
    pydantic_to_json_schema,
)
from .prompts import repo_summarizer_prompt


class DeepSeekLLMAdapter:
    """Adapter for DeepSeek API calls via Nebius TokenFactory.
    
    Supports both regular text responses and structured JSON output using response schemas.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_base: str = "https://api.tokenfactory.nebius.com/v1/chat/completions",
        model: str = "deepseek-ai/DeepSeek-V3.2",
        timeout: int = 60,
    ):
        """
        Initialize DeepSeek LLM adapter.

        Args:
            api_key: API key for DeepSeek via Nebius TokenFactory. Defaults to NEBIUS_API_KEY env var.
            api_base: Base URL for Nebius TokenFactory API endpoint (https://api.tokenfactory.nebius.com/v1/chat/completions).
            model: Model identifier (e.g., "deepseek-ai/DeepSeek-V3.2").
            timeout: Request timeout in seconds.
        """
        self.api_key = api_key or os.getenv("NEBIUS_API_KEY", "")
        self.api_base = api_base
        self.model = model
        self.timeout = timeout
        self.max_prompt_tokens = self._parse_max_tokens()

        if not self.api_key:
            raise ValueError(
                "DeepSeek API key not provided. Set NEBIUS_API_KEY environment variable."
            )

    @staticmethod
    def _parse_max_tokens() -> int:
        """Parse MAX_PROMPT_TOKENS from environment with fallback."""
        try:
            return int(os.getenv("MAX_PROMPT_TOKENS", "50000"))
        except ValueError:
            return 50000

    def _validate_prompt_tokens(self, prompt: str) -> None:
        """Validate prompt doesn't exceed token limit.
        
        Raises:
            RuntimeError: If prompt exceeds max_prompt_tokens.
        """
        try:
            enc = tiktoken.encoding_for_model(self.model)
        except KeyError:
            enc = tiktoken.get_encoding("cl100k_base")

        prompt_token_count = len(enc.encode(prompt))
        if prompt_token_count > self.max_prompt_tokens:
            raise RuntimeError(
                f"Prompt too large: {prompt_token_count} tokens (limit {self.max_prompt_tokens})"
            )

    async def call(
        self,
        prompt: str,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        response_model: Optional[type[BaseModel]] = None,
    ) -> str:
        """
        Make an async call to DeepSeek API via Nebius.

        Args:
            prompt: The prompt text to send to the LLM.
            temperature: Sampling temperature (0.0 to 2.0).
            max_tokens: Maximum tokens in the response.
            response_model: Optional Pydantic model for structured output. If provided,
                           the response will be constrained to match this schema.

        Returns:
            The LLM response as a string. If response_model is provided, a JSON string is returned.

        Raises:
            ValueError: If API key is not set.
            httpx.HTTPError: If the API request fails.
        """
        if not self.api_key:
            raise ValueError("DeepSeek API key not configured.")

        self._validate_prompt_tokens(prompt)

        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        if response_model:
            payload["response_format"] = {
                "type": "json_object",
                "schema": pydantic_to_json_schema(response_model),
            }

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout, verify=True) as client:
                response = await client.post(
                    self.api_base,
                    json=payload,
                    headers=headers,
                )
                response.raise_for_status()
        except httpx.ConnectError as e:
            raise RuntimeError(f"Failed to connect to API endpoint {self.api_base}: {e}") from e
        except httpx.TimeoutException as e:
            raise RuntimeError(f"API request timed out after {self.timeout}s: {e}") from e
        except httpx.HTTPStatusError as e:
            error_detail = getattr(e.response, 'text', '')
            raise RuntimeError(
                f"API returned status {e.response.status_code} for model '{self.model}': {error_detail}"
            ) from e

        data = response.json()
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        
        self._log_token_usage(data.get("usage", {}))
        
        return content.strip()

    @staticmethod
    def _log_token_usage(usage: dict) -> None:
        """Log token usage statistics if available."""
        prompt_tokens = usage.get("prompt_tokens", 0)
        completion_tokens = usage.get("completion_tokens", 0)
        total_tokens = usage.get("total_tokens", 0)
        
        if prompt_tokens or completion_tokens:
            print(f"Token usage - Input: {prompt_tokens}, Output: {completion_tokens}, Total: {total_tokens}")

    async def summarize_repository(self, skeleton_text: str) -> RepositorySummary:
        """
        Summarize a repository based on its code skeleton using structured output.

        Args:
            skeleton_text: Code skeleton extracted from the repository.

        Returns:
            RepositorySummary object with validated repository analysis.
        """
        prompt = repo_summarizer_prompt(skeleton_text)
        response = await self.call(
            prompt,
            max_tokens=2048,
            response_model=RepositorySummary,
        )

        try:
            data = json.loads(response)
            return RepositorySummary(**data)
        except (json.JSONDecodeError, ValueError) as e:
            raise RuntimeError(f"Failed to parse LLM response: {e}")


__all__ = [
    "DeepSeekLLMAdapter",
    "summarize_with_llm",
]


def summarize_with_llm(
    skeletons: list[Any],
    graph_analysis: Any,
    external_deps: list[str],
    entry_points: list[str],
    api_key: Optional[str] = None,
) -> str:
    if not api_key:
        return "No LLM summary (API key not provided)"

    top_files = sorted(skeletons, key=lambda s: s.line_count, reverse=True)[:15]
    file_summary = "\n".join(
        [
            f"- {s.file} ({s.line_count} lines, {len(s.functions)} functions, {len(s.classes)} classes)"
            for s in top_files
        ]
    )

    prompt = f"""
Analyze this Python codebase and write a 4-6 sentence architectural summary.

KEY FILES:
{file_summary}

CALL GRAPH ANALYSIS:
- Most called functions: {graph_analysis.most_called[:5]}
- Utility functions: {graph_analysis.utilities[:5]}
- Orchestrators: {graph_analysis.orchestrators[:5]}
- Max call depth: {graph_analysis.max_call_depth}
- Circular dependencies: {graph_analysis.circular_dependencies}

ENTRY POINTS:
{', '.join(entry_points[:5]) if entry_points else 'None found'}

EXTERNAL DEPENDENCIES:
{', '.join(external_deps[:15])}

Write a concise summary covering:
1. What the project does (infer from structure)
2. Architecture pattern (layered, monolith, etc)
3. Key components and their roles
4. Notable patterns or complexity
"""

    try:
        import anthropic

        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text.strip()
    except Exception as exc:
        return f"LLM summarization failed: {str(exc)}"
