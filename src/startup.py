"""Startup hooks to fix deployment issues."""
import subprocess
import logging

logger = logging.getLogger(__name__)

async def on_startup():
    """Ensure VPS has latest code on app start."""
    try:
        # Try to git pull on startup
        result = subprocess.run(
            ["git", "pull", "origin", "master"],
            cwd="/opt/pg-accountant",
            capture_output=True,
            text=True,
            timeout=30
        )
        if result.returncode == 0:
            logger.info("Git pull successful on startup")
        else:
            logger.warning(f"Git pull failed: {result.stderr}")
    except Exception as e:
        logger.error(f"Could not git pull on startup: {e}")

    logger.info("=== PG ACCOUNTANT STARTED ===")
