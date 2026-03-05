from __future__ import annotations

import json
import re
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
    _structured_output_disabled: bool = False

    def _split_context(self, context_text: str) -> tuple[str, str, str]:
        if not context_text:
            return "", "", ""
        text = context_text.strip()
        runtime_text = ""
        if "\n\n[Runtime]\n" in text:
            text, runtime_part = text.split("\n\n[Runtime]\n", 1)
            runtime_text = runtime_part.strip()
        if "\n\n[History]\n" in text:
            system_part, history_part = text.split("\n\n[History]\n", 1)
            system_part = system_part.replace("[System]\n", "", 1).strip()
            return system_part, history_part.strip(), runtime_text
        if text.startswith("[History]\n"):
            history_part = text.replace("[History]\n", "", 1).strip()
            return "", history_part, runtime_text
        if text.startswith("[Runtime]\n"):
            runtime_part = text.replace("[Runtime]\n", "", 1).strip()
            return "", "", runtime_part
        return text, "", runtime_text

    def generate(self, action_text: I18NText, player_id: str, context_text: str = "") -> KeeperOutput:
        prompt = self.prompt_path.read_text(encoding="utf-8") if self.prompt_path.exists() else ""
        user_text = action_text.zh or action_text.en or ""
        system_context, history_text, runtime_text = self._split_context(context_text)
        system_prompt = prompt if not system_context else f"{prompt}\n\n{system_context}"
        user_parts = []
        if history_text:
            user_parts.append(f"[History]\n{history_text}")
        if runtime_text:
            user_parts.append(f"[Runtime]\n{runtime_text}")
        user_parts.append(f"[Player {player_id}]\n{user_text}")
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": "\n\n".join(user_parts)},
        ]
        attempts = max(1, int(self.config.llm_parse_retries or 0) + 1)
        last_err: str | None = None
        for _ in range(attempts):
            content: str | None = None
            if not self._structured_output_disabled:
                try:
                    content = self._call_llm(messages, use_structured_output=True)
                except RuntimeError as exc:
                    if self._is_structured_output_unsupported(str(exc)):
                        self._structured_output_disabled = True
                    else:
                        last_err = str(exc)
            if content is None:
                content = self._call_llm(messages, use_structured_output=False)
            self.last_raw = content
            cleaned = content.strip()
            try:
                data = json.loads(cleaned)
                return KeeperOutput(**data)
            except Exception as exc:
                last_err = str(exc)
                # Fallback compatibility for providers that still return fenced/mixed text.
                cleaned = self._normalize_json_candidate(self._extract_json(content))
                try:
                    data = json.loads(cleaned)
                    return KeeperOutput(**data)
                except Exception:
                    pass
                repaired = self._repair_json(content)
                self.last_raw = repaired
                try:
                    repaired_cleaned = self._normalize_json_candidate(
                        self._extract_json(repaired)
                    )
                    data = json.loads(repaired_cleaned)
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
        system_context, history_text, runtime_text = self._split_context(context_text)
        system_prompt = prompt if not system_context else f"{prompt}\n\n{system_context}"
        user_parts = []
        if history_text:
            user_parts.append(f"[History]\n{history_text}")
        if runtime_text:
            user_parts.append(f"[Runtime]\n{runtime_text}")
        user_parts.append(prompt_text)
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": "\n\n".join(user_parts)},
        ]
        content = self._call_llm(messages, use_structured_output=False)
        self.last_raw = content
        return content.strip()

    def _call_llm(self, messages: list[dict[str, Any]], use_structured_output: bool) -> str:
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
            if use_structured_output:
                payload["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "keeper_output",
                        "strict": True,
                        "schema": self._keeper_output_json_schema(),
                    },
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
            content = data["choices"][0]["message"]["content"]
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                texts: list[str] = []
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "text":
                        text_value = item.get("text")
                        if isinstance(text_value, str):
                            texts.append(text_value)
                if texts:
                    return "".join(texts)
                return json.dumps(content, ensure_ascii=False)
            return str(content)
        except Exception as exc:
            raise RuntimeError(f"LLM response parse error: {exc}; raw={data}") from exc

    def _is_structured_output_unsupported(self, err: str) -> bool:
        text = err.lower()
        markers = (
            "response_format",
            "json_schema",
            "structured",
            "unsupported",
            "not supported",
            "invalid_request_error",
            "unknown field",
        )
        return any(m in text for m in markers)

    def _keeper_output_json_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "message_type": {
                    "type": "string",
                    "enum": ["public", "secret", "system"],
                },
                "visible_to": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "content": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "zh": {"type": ["string", "null"]},
                        "en": {"type": ["string", "null"]},
                    },
                    "required": ["zh", "en"],
                },
                "actions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "function_name": {
                                "type": "string",
                                "enum": [
                                    "roll_dice",
                                    "apply_damage",
                                    "apply_sanity_change",
                                    "update_player_attribute",
                                    "update_npc_trust",
                                    "add_item",
                                    "add_clue",
                                    "add_status",
                                    "remove_status",
                                    "oppose_check",
                                    "end_module",
                                ],
                            },
                            "parameters": {"type": "object"},
                        },
                        "required": ["function_name", "parameters"],
                    },
                },
                "notes": {},
            },
            "required": ["message_type", "visible_to", "content", "actions"],
        }

    def _extract_json(self, content: str) -> str:
        text = content.strip()
        if text.startswith("```"):
            text = text.strip("`")
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            return text[start : end + 1]
        return text

    def _normalize_json_candidate(self, text: str) -> str:
        # Common LLM failure: unescaped double quotes inside content.zh/content.en.
        # We sanitize those fields before json.loads.
        def escape_inner(raw: str) -> str:
            out: list[str] = []
            i = 0
            while i < len(raw):
                ch = raw[i]
                if ch == '"':
                    bs = 0
                    j = i - 1
                    while j >= 0 and raw[j] == "\\":
                        bs += 1
                        j -= 1
                    if bs % 2 == 0:
                        out.append('\\"')
                    else:
                        out.append('"')
                else:
                    out.append(ch)
                i += 1
            return "".join(out)

        pattern = re.compile(r'("zh"\s*:\s*")(.*?)("\s*,\s*"en"\s*:\s*")', re.DOTALL)
        text = pattern.sub(lambda m: m.group(1) + escape_inner(m.group(2)) + m.group(3), text)
        pattern_en = re.compile(r'("en"\s*:\s*")(.*?)(")', re.DOTALL)
        text = pattern_en.sub(lambda m: m.group(1) + escape_inner(m.group(2)) + m.group(3), text)
        return text

    def _repair_json(self, content: str) -> str:
        repair_prompt = (
            "你是严格的JSON修复器。只输出修复后的JSON，不要解释，不要使用代码块。"
        )
        messages = [
            {"role": "system", "content": repair_prompt},
            {"role": "user", "content": content},
        ]
        return self._call_llm(messages, use_structured_output=False)
