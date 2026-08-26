#!/usr/bin/env python3
"""Stitch MCP client đơn giản — gọi generate_screen_from_text & edit_screens.

Dùng: python3 stitch_gen.py <subcommand> ...
Yêu cầu env STITCH_KEY. Project + designSystem hardcoded (tạo rồi).
"""
import json
import os
import sys
import urllib.request

KEY = os.environ["STITCH_KEY"]
PID = "9228926018004311093"
DS = "082f3f00f61d42f7b034825534dd8216"
URL = "https://stitch.googleapis.com/mcp"
HDRS = {
    "X-Goog-Api-Key": KEY,
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
    "MCP-Protocol-Version": "2025-06-18",
}


def call(name, arguments, id=1):
    body = {"jsonrpc": "2.0", "id": id, "method": "tools/call",
            "params": {"name": name, "arguments": arguments}}
    req = urllib.request.Request(URL, data=json.dumps(body).encode("utf-8"),
                                 headers=HDRS, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            return r.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return f"HTTP {e.code}: {e.read().decode('utf-8', 'ignore')[:500]}"
    except Exception as e:
        return f"ERR {type(e).__name__}: {e}"


def gen(prompt, screen_id=None):
    args = {"projectId": PID, "prompt": prompt, "deviceType": "DESKTOP",
            "designSystem": f"assets/{DS}"}
    if screen_id:
        args["screenId"] = screen_id
    return call("generate_screen_from_text", args)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "gen"
    if cmd == "gen":
        prompt = sys.stdin.read()
        print(gen(prompt))
    elif cmd == "list_screens":
        print(call("list_screens", {"projectId": PID}))
    elif cmd == "get_screen":
        print(call("get_screen", {"projectId": PID, "screenId": sys.argv[2]}))
    else:
        print("commands: gen (stdin=prompt), list_screens, get_screen <id>")
