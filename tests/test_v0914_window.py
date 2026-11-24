"""v0.9.14: native window (pywebview) with a browser fallback; closing the window stops the app."""
import sys
import threading
import time
import types

from agent import desktop, window


class FakeEvent(list):
    def __iadd__(self, f):
        self.append(f)
        return self


class FakeWebview(types.SimpleNamespace):
    def __init__(self, fail=False, user_closes=True):
        super().__init__(settings={}, created=[], fail=fail, user_closes=user_closes)

    def create_window(self, title, url, **kw):
        win = types.SimpleNamespace(title=title, url=url, kw=kw, events=types.SimpleNamespace(closed=FakeEvent()),
                                    destroyed=False)
        win.destroy = lambda: setattr(win, "destroyed", True)
        self.created.append(win)
        return win

    def start(self, func=None, args=()):
        if self.fail:
            raise RuntimeError("WebView2 runtime missing")
        win = self.created[-1]
        if func is not None:
            threading.Thread(target=func, args=args, daemon=True).start()
        if self.user_closes:
            time.sleep(0.05)
            for f in win.events.closed:
                f()


def test_flag_and_env_force_the_browser(monkeypatch):
    monkeypatch.delenv("AGENT_NO_BROWSER", raising=False)
    monkeypatch.delenv("AGENT_BROWSER", raising=False)
    assert window.wanted(["--x"]) == (True, ["--x"])
    assert window.wanted(["--browser", "--x"]) == (False, ["--x"])
    monkeypatch.setenv("AGENT_BROWSER", "1")
    assert window.wanted([])[0] is False
    monkeypatch.delenv("AGENT_BROWSER")
    monkeypatch.setenv("AGENT_NO_BROWSER", "1")
    assert window.wanted([])[0] is False


def test_missing_pywebview_falls_back(monkeypatch):
    monkeypatch.setitem(sys.modules, "webview", None)       # import fails like a source run without it
    wv, why = window.load()
    assert wv is None and "pywebview not available" in why
    assert window.describe().startswith("window: pywebview not available")


def test_window_settings_and_close_calls_the_stop_hook():
    wv, closed = FakeWebview(), []
    assert window.run(wv, "http://127.0.0.1:1/", on_closed=lambda: closed.append(1)) is True
    w = wv.created[0]
    assert w.title == "AutonomousAgent" and w.kw["width"] == 1100 and w.kw["height"] == 750 and w.kw["resizable"]
    assert wv.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] is True and wv.settings["ALLOW_DOWNLOADS"] is True
    assert closed == [1]


def test_start_failure_returns_false_and_logs():
    logs = []
    assert window.run(FakeWebview(fail=True), "u", on_closed=lambda: None, log=logs.append) is False
    assert "WebView2" in logs[0]


def test_serve_in_window_close_stops_the_server(monkeypatch):
    """Server in a thread, window on the main thread; closing the window posts the stop request."""
    stop = threading.Event()
    posts = []
    monkeypatch.setattr(desktop, "open_when_ready", lambda url, browser=True: True)
    from agent import instance
    monkeypatch.setattr(instance, "_post", lambda url, headers, timeout: (posts.append((url, headers)), stop.set()))
    code = desktop._serve_in_window(FakeWebview(), "http://127.0.0.1:9/", 9, "tok",
                                    lambda: (stop.wait(5), 0)[1])
    assert code == 0 and posts[0][0].endswith(":9/app/takeover") and posts[0][1][instance.TOKEN_HEADER] == "tok"


def test_server_stopping_closes_the_window(monkeypatch):
    monkeypatch.setattr(desktop, "open_when_ready", lambda url, browser=True: True)
    wv = FakeWebview(user_closes=False)
    orig = wv.start

    def start(func=None, args=()):
        orig(func, args)
        for _ in range(100):           # the watcher closes the window once the server thread ends
            if wv.created[-1].destroyed:
                return
            time.sleep(0.02)
    wv.start = start
    assert desktop._serve_in_window(wv, "u", 9, "t", lambda: (time.sleep(0.3), 0)[1]) == 0
    assert wv.created[-1].destroyed


def test_window_failure_opens_the_browser(monkeypatch):
    monkeypatch.delenv("AGENT_NO_BROWSER", raising=False)
    monkeypatch.setattr(desktop, "open_when_ready", lambda url, browser=True: True)
    opened, stop = [], threading.Event()
    monkeypatch.setattr(desktop.webbrowser, "open", lambda u: (opened.append(u), stop.set()))
    assert desktop._serve_in_window(FakeWebview(fail=True), "http://x/", 9, "t", lambda: (stop.wait(5), 0)[1]) == 0
    assert opened == ["http://x/"]
