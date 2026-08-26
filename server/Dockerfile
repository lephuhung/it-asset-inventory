# Server image — Python 3.12 slim
FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# Cài dependency runtime (bám sát pyproject.toml dependencies)
COPY pyproject.toml ./
RUN pip install --no-cache-dir \
    "fastapi>=0.115.0" \
    "uvicorn[standard]>=0.30.0" \
    "pydantic>=2.7.0" \
    "pydantic-settings>=2.3.0" \
    "email-validator>=2.0.0" \
    "sqlalchemy[asyncio]>=2.0.30" \
    "asyncpg>=0.29.0" \
    "alembic>=1.13.0" \
    "redis>=5.0.0" \
    "pyjwt>=2.8.0" \
    "bcrypt>=4.1.0" \
    "cryptography>=42.0.0" \
    "pyotp>=2.9.0" \
    "jinja2>=3.1.0" \
    "slowapi>=0.1.9"

COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
