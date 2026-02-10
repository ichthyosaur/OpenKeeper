from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from threading import Lock

from app.config import AppConfig
from app.models import I18NText, KeeperOutput, MessageType


@dataclass
class KeeperLLM:
    config: AppConfig
    prompt_path: Path
    last_raw: str = ""
    last_usage: dict[str, Any] | None = None
    _lock: Lock = Lock()

    def generate(self, action_text: I18NText, player_id: str, context_text: str = "") -> KeeperOutput:
        prompt = self.prompt_path.read_text(encoding="utf-8") if self.prompt_path.exists() else ""
        user_text = action_text.zh or action_text.en or ""
        messages = [
            {"role": "system", "content": prompt},
            {
                "role": "user",
                "content": f"[Context]\n{context_text}\n\n[Player {player_id}]\n{user_text}",
            },
        ]
        attempts = max(1, int(self.config.llm_parse_retries or 0) + 1)
        last_err: str | None = None
        for _ in range(attempts):
            content = self._call_llm(messages)
            self.last_raw = content
            cleaned = self._extract_json(content)
            try:
                data = json.loads(cleaned)
                return KeeperOutput(**data)
            except Exception as exc:
                last_err = str(exc)
                repaired = self._repair_json(content)
                self.last_raw = repaired
                try:
                    data = json.loads(self._extract_json(repaired))
                    return KeeperOutput(**data)
                except Exception as exc2:
                    last_err = str(exc2)
                    time.sleep(0.5)
                    continue
        return KeeperOutput(
            message_type=MessageType.system,
            visible_to=["all"],
            content=I18NText(
                zh="LLM 输出无法解析，已忽略。",
                en="LLM output could not be parsed and was ignored.",
            ),
            actions=[],
            notes=f"llm_parse_error: {last_err or ''}".strip(),
        )

    def generate_text(self, prompt_text: str, context_text: str = "") -> str:
        prompt = self.prompt_path.read_text(encoding="utf-8") if self.prompt_path.exists() else ""
        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": f"[Context]\n{context_text}\n\n{prompt_text}"},
        ]
        content = self._call_llm(messages)
        self.last_raw = content
        return content.strip()

    def _call_llm(self, messages: list[dict[str, Any]]) -> str:
        if not self.config.api_key or not self.config.base_url:
            raise RuntimeError("LLM config missing api_key/base_url")
        with self._lock:
            url = self.config.base_url.rstrip("/") + "/chat/completions"
            payload = {
                "model": self.config.model,
                "messages": messages,
                "temperature": self.config.temperature,
                "stream": False,
            }
            headers = {"Authorization": f"Bearer {self.config.api_key}"}
            timeout = httpx.Timeout(60.0, connect=10.0)
            with httpx.Client(timeout=timeout) as client:
                resp = None
                for attempt in range(2):
                    resp = client.post(url, json=payload, headers=headers)
                    if resp.status_code < 500:
                        break
                if resp.status_code >= 400:
                    raise RuntimeError(f"LLM HTTP {resp.status_code}: {resp.text[:500]}")
                try:
                    data = resp.json()
                except Exception:
                    # Some providers return plain text even with 200; treat it as content.
                    return resp.text.strip()
        if isinstance(data, dict) and "usage" in data:
            self.last_usage = data.get("usage")
        try:
            return data["choices"][0]["message"]["content"]
        except Exception as exc:
            raise RuntimeError(f"LLM response parse error: {exc}; raw={data}") from exc

    def _extract_json(self, content: str) -> str:
        text = content.strip()
        if text.startswith("```"):
            text = text.strip("`")
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            return text[start : end + 1]
        return text

    def _repair_json(self, content: str) -> str:
        repair_prompt = (
            "你是严格的JSON修复器。只输出修复后的JSON，不要解释，不要使用代码块。"
        )
        messages = [
            {"role": "system", "content": repair_prompt},
            {"role": "user", "content": content},
        ]
        return self._call_llm(messages)
