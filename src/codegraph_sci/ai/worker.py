"""``cgs ai-worker``: the model in its own process, one JSON message per line on stdin/stdout (no port).

Request:  {"id": 1, "task": "...", "key": "...", "prompt": "...", "schema": {...}}
Response: {"id": 1, "result": {...}}  or  {"id": 1, "error": "..."}
"""

from __future__ import annotations

import json
import subprocess
import sys
from typing import Any, TextIO

from codegraph_sci.ai.models import Model, ModelError, load_model, validated


def serve(model: Model, stdin: TextIO = sys.stdin, stdout: TextIO = sys.stdout) -> int:
    print(json.dumps({"ready": True, "model": model.model_id}), file=stdout, flush=True)
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        if req.get("task") == "shutdown":
            break
        try:
            result = validated(model.generate(req["task"], req.get("key", ""), req["prompt"], req["schema"]),
                               req["schema"])
            reply: dict[str, Any] = {"id": req.get("id"), "result": result}
        except (ModelError, KeyError) as exc:
            reply = {"id": req.get("id"), "error": str(exc)}
        print(json.dumps(reply, ensure_ascii=False), file=stdout, flush=True)
    return 0


class AIClient:
    """Talks to a model: in-process (tests) or through ``cgs ai-worker`` (application)."""

    def __init__(self, model_spec: str, in_process: bool = False) -> None:
        self.model_spec = model_spec
        self.counter = 0
        self.calls = 0
        self.model: Model | None = load_model(model_spec) if in_process else None
        self.proc: subprocess.Popen[str] | None = None
        if not in_process:
            self.proc = subprocess.Popen([sys.executable, "-m", "codegraph_sci", "ai-worker", "--model", model_spec],
                                         stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, encoding="utf-8")
            assert self.proc.stdout is not None
            ready = json.loads(self.proc.stdout.readline() or "{}")
            if not ready.get("ready"):
                raise ModelError("AI worker did not start")

    def ask(self, task: str, key: str, prompt: str, schema: dict[str, Any]) -> dict[str, Any]:
        self.calls += 1
        if self.model is not None:
            return validated(self.model.generate(task, key, prompt, schema), schema)
        assert self.proc is not None and self.proc.stdin is not None and self.proc.stdout is not None
        self.counter += 1
        self.proc.stdin.write(json.dumps({"id": self.counter, "task": task, "key": key, "prompt": prompt,
                                          "schema": schema}) + "\n")
        self.proc.stdin.flush()
        reply = json.loads(self.proc.stdout.readline() or "{}")
        if "error" in reply or "result" not in reply:
            raise ModelError(str(reply.get("error", "no answer")))
        result: dict[str, Any] = reply["result"]
        return result

    def close(self) -> None:
        if self.proc is not None and self.proc.stdin is not None:
            try:
                self.proc.stdin.write(json.dumps({"task": "shutdown"}) + "\n")
                self.proc.stdin.flush()
            except OSError:
                pass
            self.proc.wait(timeout=30)
            self.proc = None
