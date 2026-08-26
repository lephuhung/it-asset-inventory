#!/usr/bin/env python3
"""Tải HTML các screen của project người dùng (1399479754615558603) qua Stitch MCP.

Dùng: python3 stitch_fetch_user.py
Yêu cầu env STITCH_KEY.
"""
import json, os, urllib.request

KEY = os.environ["STITCH_KEY"]
PID = "1399479754615558603"
URL = "https://stitch.googleapis.com/mcp"
HDRS = {"X-Goog-Api-Key": KEY, "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream", "MCP-Protocol-Version": "2025-06-18"}

# screen instances không hidden (lấy từ get_project)
SCREENS = [
    "193187c49b4d4e15aa41c1466c375fbc",  # Cấp phát Agent & Người dùng
    "23bc259483644379aa804fe3cff3e185",  # (chưa biết)
    "280adc0853294817be6ec09958e69f63",
    "28479aaa52a6453f88a38a65e1f9e355",
    "a89d7e6647a0493f8dac75075a5b99c1",
    "c261c3fd92d54f419fea3d042cb9dab4",
    "efc5ad3fa0854a84aa6494137395b970",
]

def call(name, args, rid=1):
    body = {"jsonrpc": "2.0", "id": rid, "method": "tools/call",
            "params": {"name": name, "arguments": args}}
    req = urllib.request.Request(URL, data=json.dumps(body).encode(), headers=HDRS, method="POST")
    try:
        r = urllib.request.urlopen(req, timeout=60).read().decode()
        return json.loads(r)
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}

def main():
    os.makedirs("stitch-ref/user-project", exist_ok=True)
    for i, sid in enumerate(SCREENS):
        d = call("get_screen", {"projectId": PID, "screenId": sid}, rid=i + 10)
        r = d.get("result", {})
        if r.get("isError"):
            print(f"[{i}] {sid}: LỖI {r.get('content')}")
            continue
        sc = r.get("structuredContent", {})
        title = sc.get("title", "unknown")
        url = sc.get("htmlCode", {}).get("downloadUrl")
        if not url:
            print(f"[{i}] {title}: không có html url")
            continue
        try:
            html = urllib.request.urlopen(url, timeout=40).read()
            fname = f"stitch-ref/user-project/{i:02d}_{title.replace(' ', '_')[:40]}.html"
            open(fname, "wb").write(html)
            print(f"[{i}] {title}: {len(html)} bytes → {fname}")
        except Exception as e:
            print(f"[{i}] {title}: download lỗi {e}")

if __name__ == "__main__":
    main()
