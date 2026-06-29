from google import genai
from google.genai import types


class GeminiProvider:
    DEFAULT_MODEL = "gemini-3.1-pro"

    def __init__(self, api_key: str, model: str) -> None:
        self._client = genai.Client(api_key=api_key)
        self._model = model or self.DEFAULT_MODEL
        # Token usage from the most recent call_model (Phase 3 cost tracking).
        self.last_usage: dict[str, int] | None = None

    def call_model(self, prompt: str, *, system: str | None = None) -> str:
        config = types.GenerateContentConfig(
            system_instruction=system,
        ) if system else None
        response = self._client.models.generate_content(
            model=self._model,
            contents=prompt,
            config=config,
        )
        self.last_usage = self._extract_usage(response)
        return response.text

    @staticmethod
    def _extract_usage(response: object) -> dict[str, int] | None:
        """Pull prompt/completion token counts from the response, if present."""
        meta = getattr(response, "usage_metadata", None)
        if meta is None:
            return None
        prompt = getattr(meta, "prompt_token_count", None) or 0
        completion = getattr(meta, "candidates_token_count", None) or 0
        return {"prompt_tokens": int(prompt), "completion_tokens": int(completion)}
