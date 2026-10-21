"""Temporary runtime compatibility probe; never deployed by the main configuration."""

import sqlite3

from workers import Response, WorkerEntrypoint


class Default(WorkerEntrypoint):
    async def fetch(self, request):
        import openai
        import pydantic

        connection = sqlite3.connect(":memory:")
        answer = connection.execute("SELECT 42").fetchone()[0]
        connection.close()
        return Response.json(
            {
                "sqlite": answer,
                "openai": openai.__version__,
                "pydantic": pydantic.__version__,
            }
        )
