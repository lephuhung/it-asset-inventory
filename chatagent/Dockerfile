FROM python:3.12-slim

WORKDIR /app

# mcp-velociraptor pinned to the same immutable SHA that DeepAgent uses
# (spec §"Triển khai"). The bridge is read-only; the chatagent holds no DB
# credentials and forwards Velociraptor `api_client.yaml` per request only.
ARG MCP_VELOCIRAPTOR_REF=9b3c4b3a590029390e88049896a473d7f909c0ce
ENV MCP_VELOCIRAPTOR_REF=${MCP_VELOCIRAPTOR_REF}

RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

# Clone the pinned MCP bridge into its own venv so bridge dependencies cannot
# shadow the chatagent runtime (same pattern as deepagent/Dockerfile).
RUN git clone https://github.com/lephuhung/mcp-velociraptor.git /opt/mcp-velociraptor \
    && git -C /opt/mcp-velociraptor checkout "$MCP_VELOCIRAPTOR_REF" \
    && python -m venv /opt/mcp-venv \
    && /opt/mcp-venv/bin/pip install --no-cache-dir -r /opt/mcp-velociraptor/requirements.txt \
    && /opt/mcp-venv/bin/python -m py_compile /opt/mcp-velociraptor/mcp_velociraptor_bridge.py

# Only the chatagent package is copied. The root `.env` is never present in the
# image, and compose passes CHATAGENT_* variables explicitly (spec F5).
COPY pyproject.toml ./
COPY chatagent ./chatagent
RUN pip install --no-cache-dir .

# No `EXPOSE`: the agent does not publish a port. It listens on the internal
# `inventory-net` only (spec F5 — `inventory-net` is reachability, not identity).
CMD ["uvicorn", "chatagent.api:app", "--host", "0.0.0.0", "--port", "8091"]
