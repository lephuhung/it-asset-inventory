from __future__ import annotations

import json
from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="DEEPAGENT_",
        extra="ignore",
    )

    host: str = "0.0.0.0"
    port: int = 8090
    service_token: str = "CHANGE_ME_service_token"
    max_concurrent_jobs: int = 2

    backend_url: str = "http://127.0.0.1:8000"
    backend_api_key: str = ""

    llm_base_url: str = "http://127.0.0.1:11434/v1"
    llm_api_key: str = "ollama"
    llm_model: str = "qwen2.5:14b-instruct-q4_K_M"
    llm_timeout_seconds: int = 180

    mcp_transport: str = "stdio"
    mcp_command: str = "python"
    mcp_args_json: str = "[]"
    mcp_env_json: str = "{}"
    velociraptor_org_id: str = ""

    max_steps: int = 6  # Ordinary plan sanitization; graph may add max 2 detail calls after triage
    max_evidence_chars: int = 120_000
    max_tool_result_chars: int = 30_000

    # Caller deadline for every MCP tool invocation. A DeepAgent timeout is
    # only proof that the MCP call did not return before the deadline; it is
    # NOT a Velociraptor flow-level guarantee. Phase 2 will add flow-level
    # diagnosis through a tracked bridge patch/fork.
    mcp_tool_timeout_seconds: int = Field(default=180, ge=10, le=1800)

    @field_validator("mcp_transport")
    @classmethod
    def validate_transport(cls, value: str) -> str:
        if value != "stdio":
            raise ValueError("Phiên bản hiện tại chỉ hỗ trợ MCP transport=stdio")
        return value

    def mcp_args(self) -> list[str]:
        value = json.loads(self.mcp_args_json)
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise ValueError("DEEPAGENT_MCP_ARGS_JSON phải là JSON array chứa chuỗi")
        return value

    def mcp_env(self) -> dict[str, str]:
        value = json.loads(self.mcp_env_json)
        if not isinstance(value, dict) or not all(
            isinstance(key, str) and isinstance(item, str) for key, item in value.items()
        ):
            raise ValueError("DEEPAGENT_MCP_ENV_JSON phải là JSON object chuỗi → chuỗi")
        value["ENABLE_DANGEROUS_TOOLS"] = "false"
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
