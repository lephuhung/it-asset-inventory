"""Seed and push the curated Custom.DFIR.* artifact bundle.

Run from server/ with:
    .venv/bin/python -m scripts.seed_velociraptor_artifacts
"""
from __future__ import annotations

import asyncio

from app.api.routes.velociraptor import _build_velociraptor_client
from app.db.session import AsyncSessionLocal
from app.services.velociraptor_artifact_seed import seed_velociraptor_artifacts


async def main() -> None:
    async with AsyncSessionLocal() as db:
        built = await _build_velociraptor_client(db)
        if built is None:
            raise RuntimeError("Velociraptor chưa được cấu hình bằng api_client.yaml")
        client, _cfg = built
        async with client:
            names = await seed_velociraptor_artifacts(db, client)
    print(f"Seeded and verified {len(names)} artifacts")
    for name in names:
        print(f"- {name}")


if __name__ == "__main__":
    asyncio.run(main())
