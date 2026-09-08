#!/usr/bin/env python3
"""Minimal CDP (Chrome DevTools Protocol) client.

HTTP endpoints on 127.0.0.1:9222:
  GET  /json/list          -> target list (tabs have type == "page")
  PUT  /json/new?url=<url> -> open a new tab

WebSocket: request/response with monotonic ids; event frames are skipped.
"""
import json
import time
import urllib.parse
import urllib.request

from websocket import create_connection  # websocket-client

HTTP = "http://127.0.0.1:9222"


def _preferred_hosts():
    """Hosts that win tab-selection priority: $TARGET_URL's host, then z.ai."""
    hosts = []
    import os

    target = os.environ.get("TARGET_URL", "https://chat.z.ai/")
    try:
        from urllib.parse import urlparse

        h = urlparse(target).host or urlparse(target).netloc
        if h:
            hosts.append(h)
    except Exception:
        pass
    hosts.append("chat.z.ai")
    return hosts


def _http_json(path, method="GET", timeout=5):
    req = urllib.request.Request(HTTP + path, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def list_tabs():
    """All targets of type 'page' (empty list if Chrome is down)."""
    try:
        targets = _http_json("/json/list")
    except Exception:
        return []
    return [t for t in targets if t.get("type") == "page"]


def new_tab(url):
    """Open a new tab; returns the target dict."""
    try:
        return _http_json(
            "/json/new?url=" + urllib.parse.quote(url, safe=""), method="PUT"
        )
    except urllib.error.HTTPError:
        # older builds only accept GET
        return _http_json(
            "/json/new?url=" + urllib.parse.quote(url, safe=""), method="GET"
        )


def find_tab(pattern=None, tabs=None):
    """Match URL substring; else prefer the target site (chat.z.ai by default);
    else first tab."""
    tabs = list_tabs() if tabs is None else tabs
    if not tabs:
        return None
    if pattern:
        for t in tabs:
            if pattern in t.get("url", "") or pattern in t.get("title", ""):
                return t
    for host in _preferred_hosts():
        for t in tabs:
            if host in t.get("url", ""):
                return t
    return tabs[0]


class CDP:
    """Tiny CDP session over one websocket (bound to a single tab)."""

    def __init__(self, ws_url, timeout=15):
        # suppress_origin: Chrome DevTools rejects WS handshakes that carry an
        # Origin header (403) unless --remote-allow-origins is passed.
        self.ws = create_connection(ws_url, timeout=timeout, suppress_origin=True)
        self._id = 0

    def call(self, method, params=None):
        self._id += 1
        rid = self._id
        self.ws.send(json.dumps({"id": rid, "method": method, "params": params or {}}))
        deadline = time.time() + 12
        while time.time() < deadline:
            raw = self.ws.recv()
            if not raw:
                continue
            msg = json.loads(raw)
            if msg.get("id") != rid:
                continue  # skip event frames / unrelated responses
            if "error" in msg:
                err = msg["error"]
                raise RuntimeError(f"CDP error: {err.get('message')} ({err.get('code')})")
            return msg.get("result", {})
        raise TimeoutError(f"CDP call timed out: {method}")

    def eval(self, expression, await_promise=False):
        """Runtime.evaluate with returnByValue; returns the JS value."""
        res = self.call(
            "Runtime.evaluate",
            {
                "expression": expression,
                "returnByValue": True,
                "awaitPromise": await_promise,
            },
        )
        if res.get("exceptionDetails"):
            det = res["exceptionDetails"]
            raise RuntimeError(f"eval failed: {det.get('text')}")
        return res.get("result", {}).get("value")

    def close(self):
        try:
            self.ws.close()
        except Exception:
            pass
