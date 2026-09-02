FROM python:3.12-slim

WORKDIR /app
ARG MCP_VELOCIRAPTOR_REF=37375a0c1850a327818ccfee128229a995a9625b
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*
RUN git clone https://github.com/lephuhung/mcp-velociraptor.git /opt/mcp-velociraptor \
    && git -C /opt/mcp-velociraptor checkout "$MCP_VELOCIRAPTOR_REF" \
    && python -m venv /opt/mcp-venv \
    && /opt/mcp-venv/bin/pip install --no-cache-dir -r /opt/mcp-velociraptor/requirements.txt
# Apply bounded event-log bridge patch
COPY patches/mcp-velociraptor-bounded-event-log.patch /tmp/
RUN git -C /opt/mcp-velociraptor apply --recount /tmp/mcp-velociraptor-bounded-event-log.patch \
    && python3 -m py_compile /opt/mcp-velociraptor/mcp_velociraptor_bridge.py
COPY pyproject.toml ./
COPY deepagent ./deepagent
RUN pip install --no-cache-dir .

EXPOSE 8090
CMD ["uvicorn", "deepagent.api:app", "--host", "0.0.0.0", "--port", "8090"]
