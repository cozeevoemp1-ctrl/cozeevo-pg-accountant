"""
Tests for services/room_transfer.py — runnable without a live DB.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.mark.asyncio
async def test_room_not_found():
    """session.scalar returns None for Room lookup → success=False, 'not found' in message."""
    from services.room_transfer import execute_room_transfer

    session = AsyncMock()
    session.scalar = AsyncMock(return_value=None)  # room not found

    result = await execute_room_transfer(
        tenancy_id=1,
        to_room_number="999",
        new_rent=15000,
        extra_deposit=0,
        changed_by="pwa",
        source="pwa",
        session=session,
    )

    assert result["success"] is False
    assert "not found" in result["message"].lower()


def test_import():
    """Module imports cleanly."""
    import services.room_transfer  # noqa: F401
    assert hasattr(services.room_transfer, "execute_room_transfer")
