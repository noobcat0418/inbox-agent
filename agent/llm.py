"""Thin client for any OpenAI-compatible endpoint. Default is local Ollama, so mail stays on this PC."""
from openai import OpenAI


class LLM:
    def __init__(self, cfg):
        self.model = cfg.llm_model
        self.base_url = cfg.llm_base_url
        # A 3B model on CPU can take a while on a long email.
        self.client = OpenAI(base_url=cfg.llm_base_url, api_key=cfg.llm_api_key, timeout=180)

    def complete_json(self, system: str, user: str) -> str:
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=0,
            response_format={"type": "json_object"},
        )
        return resp.choices[0].message.content or ""

    def check(self) -> str:
        """Raise if the endpoint is unreachable. Returns a warning if the model isn't pulled."""
        available = [m.id for m in self.client.models.list().data]
        if self.model not in available:
            return f"model {self.model!r} not found at {self.base_url} - run: ollama pull {self.model}"
        return ""
