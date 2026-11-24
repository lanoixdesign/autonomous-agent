"""A tiny fake Ollama for the tests and the screenshots: /api/tags, /api/show, /v1/chat/completions.
`python3 tests/fake_ollama.py 11434` serves it on that port."""
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MODELS = {"qwen2.5:7b": ["completion", "tools"], "llama3.1:8b": ["completion", "tools"], "gemma:2b": ["completion"]}


class FakeOllama:
    def __init__(self, models=None, port=0):
        self.models = dict(MODELS if models is None else models)
        self.calls: list[dict] = []
        self.auth: list[str] = []
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _json(self, code, obj):
                body = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                if self.path == "/api/tags":
                    return self._json(200, {"models": [{"name": n, "model": n, "size": 4_700_000_000}
                                                       for n in outer.models]})
                if self.path == "/":
                    return self._json(200, {"status": "Ollama is running"})
                self._json(404, {"error": "not found"})

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
                outer.auth.append(self.headers.get("Authorization") or "")
                if self.path == "/api/show":
                    caps = outer.models.get(body.get("model"))
                    if caps is None:
                        return self._json(404, {"error": "model not found"})
                    return self._json(200, {"capabilities": caps, "template": "{{ .Prompt }}"})
                if self.path == "/v1/chat/completions":
                    outer.calls.append(body)
                    m = body.get("model")
                    if m not in outer.models:
                        return self._json(404, {"error": {"message": f"model \"{m}\" not found, try pulling it first"}})
                    if body.get("tools") and "tools" not in outer.models[m]:
                        return self._json(400, {"error": {"message": f"registry.ollama.ai/library/{m} does not support tools",
                                                          "type": "api_error"}})
                    return self._json(200, {"id": "c1", "object": "chat.completion", "model": m,
                                            "choices": [{"index": 0, "finish_reason": "stop",
                                                         "message": {"role": "assistant", "content": "Bonjour depuis " + m}}],
                                            "usage": {"prompt_tokens": 12, "completion_tokens": 4}})
                self._json(404, {"error": "not found"})

        self.srv = ThreadingHTTPServer(("127.0.0.1", port), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.address = f"http://127.0.0.1:{self.srv.server_address[1]}"

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()


if __name__ == "__main__":
    f = FakeOllama(port=int(sys.argv[1]) if len(sys.argv) > 1 else 11434)
    print("fake ollama on", f.address, flush=True)
    threading.Event().wait()
