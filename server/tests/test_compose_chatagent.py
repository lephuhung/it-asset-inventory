"""Deployment wiring assertions (Task 16) — compose + Dockerfile + .env.example.

Thuần config, không cần DB: parse `docker-compose.yml` và `chatagent/Dockerfile`
để bảo đảm ranh giới cô lập môi trường (spec F5) và pin mcp-velociraptor (spec
§"Triển khai") không bị hồi quy.
"""
from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
COMPOSE_PATH = ROOT / "docker-compose.yml"
DOCKERFILE_PATH = ROOT / "chatagent" / "Dockerfile"
ENV_EXAMPLE_PATH = ROOT / ".env.example"

PINNED_MCP_REF = "9b3c4b3a590029390e88049896a473d7f909c0ce"


def _chatagent_service() -> dict:
    compose = yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))
    services = compose["services"]
    assert "chatagent" in services, "compose thiếu service chatagent"
    return services["chatagent"]


def test_chatagent_publishes_no_port() -> None:
    """Agent không publish port — chỉ reachable trên inventory-net (spec F5)."""
    service = _chatagent_service()
    assert not service.get("ports"), f"chatagent không được publish port: {service.get('ports')!r}"


def test_chatagent_does_not_load_root_env_file() -> None:
    """KHÔNG `env_file` (đặc biệt root `.env`) — biến truyền tường minh (spec F5)."""
    service = _chatagent_service()
    assert "env_file" not in service, "chatagent không được dùng env_file (root .env)"


def test_chatagent_environment_is_only_chatagent_prefixed() -> None:
    """Mọi biến môi trường phải là `CHATAGENT_*` (spec F5)."""
    service = _chatagent_service()
    env = service.get("environment") or {}
    keys = [item.split("=", 1)[0] for item in env] if isinstance(env, list) else list(env)
    assert keys, "chatagent thiếu environment"
    unprefixed = [key for key in keys if not key.startswith("CHATAGENT_")]
    assert not unprefixed, f"biến không thuộc CHATAGENT_*: {unprefixed}"


def test_chatagent_on_inventory_net_and_depends_on_api() -> None:
    service = _chatagent_service()
    networks = service.get("networks") or []
    assert "inventory-net" in list(networks)

    depends_on = service.get("depends_on") or {}
    assert "api" in list(depends_on)


def test_chatagent_build_pins_mcp_velociraptor_ref() -> None:
    """`MCP_VELOCIRAPTOR_REF` phải giữ nguyên SHA đã pin."""
    service = _chatagent_service()
    build = service.get("build") or {}
    args = build.get("args") or {}
    ref = str(args.get("MCP_VELOCIRAPTOR_REF", ""))
    assert PINNED_MCP_REF in ref, f"MCP_VELOCIRAPTOR_REF không chứa SHA pin: {ref!r}"


def test_dockerfile_pins_mcp_velociraptor_and_exposes_no_port() -> None:
    assert DOCKERFILE_PATH.exists(), "thiếu chatagent/Dockerfile"
    text = DOCKERFILE_PATH.read_text(encoding="utf-8")
    assert f"ARG MCP_VELOCIRAPTOR_REF={PINNED_MCP_REF}" in text
    assert "git clone" in text and "checkout" in text
    # Không publish/khai báo port ra ngoài (bỏ qua dòng comment).
    instructions = [
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    assert not any(line.startswith("EXPOSE") for line in instructions)
    # Chỉ copy chatagent/ — không copy toàn repo (sẽ mang theo root .env).
    assert "COPY chatagent ./chatagent" in text
    assert "COPY . ." not in text
    assert "COPY .env" not in text


def test_env_example_documents_chatagent_section() -> None:
    text = ENV_EXAMPLE_PATH.read_text(encoding="utf-8")
    for key in (
        "CHATAGENT_SERVICE_TOKEN",
        "CHATAGENT_BACKEND_URL",
        "CHATAGENT_BACKEND_API_KEY",
        "CHATAGENT_MAX_TOOL_CALLS",
        "CHATAGENT_WALL_CLOCK_SECONDS",
        "MCP_VELOCIRAPTOR_REF",
    ):
        assert key in text, f".env.example thiếu {key}"
    assert PINNED_MCP_REF in text
