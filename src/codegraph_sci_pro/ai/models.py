"""Language models for the local AI (Pro). Every answer is a JSON object constrained by a schema.

* ``FakeModel``: recorded answers (tests and CI, deterministic, no model file);
* ``LlamaModel``: a GGUF model run on CPU by ``llama-cpp-python`` (temperature 0, fixed seed),
  imported only when used. No network access, no port.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Protocol

import jsonschema


class ModelError(RuntimeError):
    pass


class Model(Protocol):
    model_id: str

    def generate(self, task: str, key: str, prompt: str, schema: dict[str, Any]) -> dict[str, Any]: ...


class FakeModel:
    """Answers read from ``responses.json``: ``{task: {key: answer}}``."""

    def __init__(self, responses: Path) -> None:
        self.model_id = f"fake:{responses.name}"
        self.responses: dict[str, dict[str, Any]] = json.loads(responses.read_text(encoding="utf-8"))
        self.calls: list[tuple[str, str]] = []

    def generate(self, task: str, key: str, prompt: str, schema: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((task, key))
        try:
            answer = self.responses[task][key]
        except KeyError as exc:
            raise ModelError(f"no recorded answer for task '{task}', key '{key}'") from exc
        if not isinstance(answer, dict):
            raise ModelError(f"recorded answer for {task}/{key} is not an object")
        return answer


class LlamaModel:
    """GGUF model on CPU. Generation is constrained by the JSON schema (the answer is always valid)."""

    def __init__(self, path: Path, n_ctx: int = 8192, seed: int = 0) -> None:
        try:
            from llama_cpp import Llama
        except ImportError as exc:  # pragma: no cover - depends on the AI edition
            raise ModelError("llama-cpp-python is not installed (AI edition only)") from exc
        threads = max(1, (os.cpu_count() or 2) - 1)
        self.model_id = path.name
        self.llm = Llama(model_path=str(path), n_ctx=n_ctx, n_threads=threads, seed=seed, verbose=False)

    def generate(self, task: str, key: str, prompt: str, schema: dict[str, Any]) -> dict[str, Any]:
        out = self.llm.create_chat_completion(
            messages=[{"role": "system", "content": "You answer with a single JSON object, nothing else."},
                      {"role": "user", "content": prompt}],
            response_format={"type": "json_object", "schema": schema}, temperature=0.0, seed=0, max_tokens=1500)
        text = out["choices"][0]["message"]["content"]
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ModelError(f"model answer is not JSON: {text[:200]}") from exc
        if not isinstance(data, dict):
            raise ModelError("model answer is not a JSON object")
        return data


def validated(answer: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
    errors = sorted(jsonschema.Draft202012Validator(schema).iter_errors(answer), key=str)
    if errors:
        raise ModelError(f"answer does not follow the schema: {errors[0].message}")
    return answer


def load_model(spec: str) -> Model:
    """``fake:<responses.json>`` or the path of a ``.gguf`` file."""
    if spec.startswith("fake:"):
        return FakeModel(Path(spec[5:]))
    path = Path(spec)
    if not path.is_file():
        raise ModelError(f"model file not found: {path}")
    return LlamaModel(path)
