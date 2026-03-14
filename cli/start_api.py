"""
CLI: start-api
Starts the FastAPI server with uvicorn.
"""
import os
import click
from dotenv import load_dotenv

load_dotenv()


@click.command("start-api")
@click.option("--host",    default=None, help="Host (default: from .env or 0.0.0.0)")
@click.option("--port",    default=None, type=int, help="Port (default: from .env or 8000)")
@click.option("--reload",  is_flag=True, help="Enable hot-reload (development mode)")
@click.option("--workers", default=1, type=int, help="Worker count (production)")
def start_api(host: str | None, port: int | None, reload: bool, workers: int):
    """
    Start the PG Accountant FastAPI server.

    Examples:\n
        python -m cli.start_api\n
        python -m cli.start_api --reload\n
        python -m cli.start_api --port 9000 --workers 2
    """
    import uvicorn
    h = host  or os.getenv("API_HOST", "0.0.0.0")
    p = port  or int(os.getenv("API_PORT", "8000"))

    print(f"Starting PG Accountant API on http://{h}:{p}")
    uvicorn.run(
        "main:app",
        host=h,
        port=p,
        reload=reload,
        workers=1 if reload else workers,
        log_level=os.getenv("LOG_LEVEL", "info").lower(),
    )


if __name__ == "__main__":
    start_api()
