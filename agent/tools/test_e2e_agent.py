#!/usr/bin/env python3
"""Script kiểm tra tự động Agent End-to-End:
1. Khởi động Mock Server tại cổng ngẫu nhiên.
2. Tạo thư mục tạm cách ly cho Agent.
3. Chạy Agent với cờ `--data-dir ... --endpoint http://127.0.0.1:<port> --enroll-token test_token_12345678 --once`.
4. Kiểm tra và xác nhận:
   - Enroll thành công: tạo machine_id, cài đặt client cert.
   - Tự động lấy config từ server (/api/agent/config): lưu heartbeat_interval, jitter, inventory_interval, renew_percent, agent_config_hash.
   - Gửi Heartbeat thành công.
   - Thu thập và gửi toàn bộ Inventory thành công.
   - Xác thực schema Pydantic các payload.
5. In kết quả chi tiết.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tools.mock_server import HOST, load_schemas, make_handler
from http.server import ThreadingHTTPServer

def run_test():
    sys.stdout.reconfigure(encoding='utf-8')
    temp_dir = Path(tempfile.mkdtemp(prefix="agent_e2e_"))
    log_file = temp_dir / "mock_requests.jsonl"
    print(f"[*] Thư mục test tạm: {temp_dir}")

    # 1. Start mock server
    models = load_schemas("")
    server = ThreadingHTTPServer((HOST, 0), make_handler(models, str(log_file), f"http://{HOST}"))
    port = server.server_port
    server_url = f"http://{HOST}:{port}"
    print(f"[*] Mock server đang lắng nghe tại: {server_url}")

    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()

    # 2. Run agent --once
    dotnet_path = Path(os.path.expanduser(r"~\.dotnet\dotnet.exe"))
    agent_dll = Path("src/OrgInventoryAgent/bin/Release/net8.0/OrgInventoryAgent.dll").resolve()

    cmd = [
        str(dotnet_path),
        str(agent_dll),
        "--data-dir", str(temp_dir),
        "--endpoint", server_url,
        "--enroll-token", "test_token_12345678",
        "--once"
    ]

    print(f"[*] Chạy Agent: {' '.join(cmd)}")
    start_time = time.time()
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", timeout=45)
    duration = time.time() - start_time

    print(f"[*] Agent kết thúc sau {duration:.2f}s với exit code: {proc.returncode}")
    print("--- STDOUT ---")
    print(proc.stdout)
    if proc.stderr:
        print("--- STDERR ---")
        print(proc.stderr)

    # 3. Analyze results
    config_file = temp_dir / "config.json"
    state_file = temp_dir / "state.json"

    assert config_file.exists(), "config.json không được tạo!"
    with open(config_file, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    machine_id = cfg.get("machineId") or cfg.get("machine_id")
    enrolled = cfg.get("enrolled")
    thumbprint = cfg.get("clientCertThumbprint") or cfg.get("client_cert_thumbprint")
    store_loc = cfg.get("certStoreLocation") or cfg.get("cert_store_location")
    hb_interval = cfg.get("heartbeatIntervalSeconds") or cfg.get("heartbeat_interval_seconds")
    hb_jitter = cfg.get("heartbeatJitterSeconds") or cfg.get("heartbeat_jitter_seconds")
    inv_hours = cfg.get("inventoryIntervalHours") or cfg.get("inventory_interval_hours")
    renew_pct = cfg.get("renewBeforePercent") or cfg.get("renew_before_percent")

    print("\n========================================================")
    print("           KẾT QUẢ KIỂM TRA ĐỒNG BỘ AGENT               ")
    print("========================================================")
    print(f"1. Trạng thái Enroll: enrolled={enrolled}, machine_id={machine_id}")
    print(f"   Thumbprint cert: {thumbprint} (Store: {store_loc})")
    assert enrolled is True, "Agent chưa enroll!"
    assert machine_id, "Thiếu machine_id!"
    assert thumbprint, "Thiếu client cert thumbprint!"

    print(f"\n2. Tính năng tự lấy config từ server (/api/agent/config):")
    print(f"   - Heartbeat interval: {hb_interval}s (từ server)")
    print(f"   - Heartbeat jitter:   {hb_jitter}s (từ server)")
    print(f"   - Inventory interval: {inv_hours}h (từ server)")
    print(f"   - Renew threshold:    {renew_pct}% (từ server)")
    
    assert hb_interval == 30, "Sai heartbeat_interval_seconds!"
    assert hb_jitter == 8, "Sai heartbeat_jitter_seconds!"

    if state_file.exists():
        with open(state_file, "r", encoding="utf-8") as f:
            state = json.load(f)
        last_cfg_hash = state.get("lastAgentConfigHash") or state.get("last_agent_config_hash")
        last_inv_at = state.get("lastInventoryAt") or state.get("last_inventory_at")
        last_inv_hash = state.get("lastInventoryConfigHash") or state.get("last_inventory_config_hash")
        print(f"   - LastAgentConfigHash: {last_cfg_hash}")
        print(f"   - LastInventoryAt:     {last_inv_at}")
        print(f"   - LastInventoryConfigHash: {last_inv_hash}")
        assert last_cfg_hash == "mock_cfg_hash_v1", "Thiếu hoặc sai lastAgentConfigHash!"
        assert last_inv_hash, "Thiếu lastInventoryConfigHash!"

    # Check mock server request logs
    assert log_file.exists(), "Không có request nào được gửi đến mock server!"
    with open(log_file, "r", encoding="utf-8") as f:
        content = f.read()
    
    entries = [json.loads(p.strip()) for p in content.split("\n---\n") if p.strip()]
    paths = [e["path"] for e in entries]
    print(f"\n3. Các request Agent đã gửi lên Server: {paths}")
    for e in entries:
        print(f"   + {e['method']} {e['path']} -> Schema: {e.get('schema')}")

    assert "/api/enroll" in paths, "Thiếu POST /api/enroll"
    assert "/api/agent/config" in paths, "Thiếu GET /api/agent/config"
    assert "/api/heartbeat" in paths, "Thiếu POST /api/heartbeat"
    assert "/api/inventory" in paths, "Thiếu POST /api/inventory"

    print("\n===> TẤT CẢ KIỂM TRA ĐỒNG BỘ CONFIG & AGENT FLOW ĐỀU THÀNH CÔNG (PASS)!")

    # Cleanup temp
    server.shutdown()
    try:
        shutil.rmtree(temp_dir)
    except Exception:
        pass

if __name__ == "__main__":
    run_test()
