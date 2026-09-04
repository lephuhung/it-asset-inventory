FROM python:3.12-slim

WORKDIR /app
ARG MCP_VELOCIRAPTOR_REF=9b3c4b3a590029390e88049896a473d7f909c0ce
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*
RUN git clone https://github.com/lephuhung/mcp-velociraptor.git /opt/mcp-velociraptor \
    && git -C /opt/mcp-velociraptor checkout "$MCP_VELOCIRAPTOR_REF" \
    && python -m venv /opt/mcp-venv \
    && /opt/mcp-venv/bin/pip install --no-cache-dir -r /opt/mcp-velociraptor/requirements.txt \
    && /opt/mcp-venv/bin/python -m py_compile /opt/mcp-velociraptor/mcp_velociraptor_bridge.py
ENV DEEPAGENT_MCP_COMMAND=/opt/mcp-venv/bin/python \
    VELOCIRAPTOR_DEFAULT_LIMIT=100 \
    VELOCIRAPTOR_MAX_LIMIT=1000
COPY pyproject.toml ./
COPY deepagent ./deepagent
RUN pip install --no-cache-dir .

EXPOSE 8090
CMD ["uvicorn", "deepagent.api:app", "--host", "0.0.0.0", "--port", "8090"]
