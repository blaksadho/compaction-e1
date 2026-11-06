"""Chat-completion backends. Both speak the OpenAI chat-completions schema.

- `http`: any OpenAI-compatible server (llama.cpp `llama-server`, vLLM, Ollama `/v1`).
- `omp-gateway`: one long-lived `omp auth-gateway stdio` subprocess that forwards to providers with the user's
  stored omp credentials. Requests are multiplexed by id, so concurrent chains share one process. The exact
  system prompt we send is the system prompt the model sees (no harness-injected prompt).
Costs are computed from the per-million-token prices in the run config, because neither transport reports cost.
"""

from __future__ import annotations

import itertools
import json
import subprocess
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import Future
from dataclasses import dataclass


class BackendError(RuntimeError):
    def __init__(self, status: int, body: object):
        super().__init__(f"backend status {status}: {str(body)[:500]}")
        self.status = status


RETRYABLE = {408, 409, 429, 500, 502, 503, 504, 529}


@dataclass
class Completion:
    text: str
    finish_reason: str | None
    input_tokens: int
    output_tokens: int
    cost_usd: float
    latency_s: float
    attempts: int
    model: str


class _HttpTransport:
    def __init__(self, base_url: str, timeout_s: float, api_key: str | None = None):
        self.url = base_url.rstrip("/") + "/chat/completions"
        self.timeout_s = timeout_s
        self.api_key = api_key

    def send(self, body: dict) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        req = urllib.request.Request(self.url, data=json.dumps(body).encode(), headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            raise BackendError(e.code, e.read().decode(errors="replace")) from None
        except (urllib.error.URLError, TimeoutError) as e:
            raise BackendError(503, repr(e)) from None

    def close(self) -> None:
        pass


class _OmpGatewayTransport:
    def __init__(self, timeout_s: float, command: list[str] | None = None):
        self.timeout_s = timeout_s
        self.proc = subprocess.Popen(command or ["omp", "auth-gateway", "stdio"], stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1)
        ready = json.loads(self.proc.stdout.readline() or "{}")
        if not ready.get("ready"):
            raise RuntimeError(f"omp auth-gateway stdio did not become ready: {ready}")
        self.version = ready.get("version")
        self._ids = itertools.count(1)
        self._pending: dict[int, Future] = {}
        self._lock = threading.Lock()
        threading.Thread(target=self._read_loop, daemon=True).start()

    def _read_loop(self) -> None:
        for line in self.proc.stdout:
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            with self._lock:
                fut = self._pending.pop(msg.get("id"), None)
            if fut is not None:
                fut.set_result(msg)
        with self._lock:  # process exited: fail everything still waiting
            for fut in self._pending.values():
                fut.set_exception(BackendError(503, "omp auth-gateway exited"))
            self._pending.clear()

    def send(self, body: dict) -> dict:
        req_id = next(self._ids)
        fut: Future = Future()
        with self._lock:
            self._pending[req_id] = fut
            self.proc.stdin.write(json.dumps({"id": req_id, "path": "/v1/chat/completions", "body": body}) + "\n")
            self.proc.stdin.flush()
        try:
            msg = fut.result(timeout=self.timeout_s)
        except TimeoutError:
            with self._lock:
                self._pending.pop(req_id, None)
            raise BackendError(408, "gateway request timed out") from None
        if msg.get("status") != 200:
            raise BackendError(int(msg.get("status") or 500), msg.get("body"))
        return msg["body"]

    def close(self) -> None:
        if self.proc.poll() is None:
            self.proc.stdin.close()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()


class ChatBackend:
    """`cfg` keys: transport ('http'|'omp-gateway'), model, base_url (http), temperature, prices_per_mtok
    [input, output], timeout_s, max_attempts."""

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.model = cfg["model"]
        timeout = float(cfg.get("timeout_s", 600))
        if cfg["transport"] == "http":
            self.transport = _HttpTransport(cfg["base_url"], timeout, cfg.get("api_key"))
        elif cfg["transport"] == "omp-gateway":
            self.transport = _OmpGatewayTransport(timeout)
        else:
            raise ValueError(f"unknown transport {cfg['transport']!r}")
        self.price_in, self.price_out = cfg.get("prices_per_mtok", [0.0, 0.0])
        self.max_attempts = int(cfg.get("max_attempts", 5))

    def complete(self, system: str, user: str, max_tokens: int) -> Completion:
        body = {"model": self.model, "max_tokens": max_tokens,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
        if self.cfg.get("temperature") is not None:
            body["temperature"] = self.cfg["temperature"]
        if self.cfg.get("seed") is not None:
            body["seed"] = self.cfg["seed"]
        start = time.monotonic()
        for attempt in range(1, self.max_attempts + 1):
            try:
                resp = self.transport.send(body)
                break
            except BackendError as e:
                if e.status not in RETRYABLE or attempt == self.max_attempts:
                    raise
                time.sleep(min(60.0, 2.0 ** attempt))
        choice = resp["choices"][0]
        usage = resp.get("usage") or {}
        tin, tout = int(usage.get("prompt_tokens", 0)), int(usage.get("completion_tokens", 0))
        return Completion(
            text=choice["message"].get("content") or "",
            finish_reason=choice.get("finish_reason"),
            input_tokens=tin,
            output_tokens=tout,
            cost_usd=(tin * self.price_in + tout * self.price_out) / 1e6,
            latency_s=time.monotonic() - start,
            attempts=attempt,
            model=resp.get("model", self.model),
        )

    def close(self) -> None:
        self.transport.close()
