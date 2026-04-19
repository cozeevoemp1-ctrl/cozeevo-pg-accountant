"""
LearningAgent — background async agent that learns from every interaction.

Runs after every LLM classification (non-blocking). Responsibilities:
1. Log classification to classification_log
2. Save confirmed examples to intent_examples
3. Auto-confirm high-confidence results that weren't corrected
4. Handle user corrections, selections, and clarifications

Each PG learns independently (scoped by pg_id).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from loguru import logger
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import IntentExample, ClassificationLog


def should_auto_confirm(confidence: float, was_corrected: bool) -> bool:
    """High-confidence classifications that weren't corrected can be auto-confirmed."""
    return confidence > 0.9 and not was_corrected


def build_example_record(
    pg_id: str,
    message: str,
    intent: str,
    role: str,
    entities: dict,
    confidence: float,
    source: str,
    confirmed_by: str,
) -> dict:
    """Build a dict suitable for inserting into intent_examples."""
    return {
        "id": str(uuid.uuid4()),
        "pg_id": pg_id,
        "message_text": message,
        "intent": intent,
        "role": role,
        "entities": entities,
        "confidence": confidence,
        "source": source,
        "confirmed_by": confirmed_by,
        "is_active": True,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }


async def log_classification(
    pg_id: str,
    message: str,
    phone: str,
    role: str,
    regex_result: Optional[str],
    regex_confidence: Optional[float],
    llm_result: Optional[str],
    llm_confidence: Optional[float],
    final_intent: str,
    session: AsyncSession,
) -> str:
    """Log a classification to the audit trail. Returns the classification_log ID."""
    log_id = str(uuid.uuid4())
    try:
        await session.execute(
            insert(ClassificationLog).values(
                id=log_id,
                pg_id=pg_id,
                message_text=message,
                phone=phone,
                role=role,
                regex_result=regex_result,
                regex_confidence=regex_confidence,
                llm_result=llm_result,
                llm_confidence=llm_confidence,
                final_intent=final_intent,
                was_corrected=False,
                created_at=datetime.now(timezone.utc),
            )
        )
        await session.commit()
        logger.debug(f"[LearningAgent] Logged classification: {final_intent} for {phone}")
    except Exception as e:
        logger.error(f"[LearningAgent] Failed to log classification: {e}")
        await session.rollback()
    return log_id


async def save_example(
    pg_id: str,
    message: str,
    intent: str,
    role: str,
    entities: dict,
    confidence: float,
    source: str,
    confirmed_by: str,
    session: AsyncSession,
) -> None:
    """Save a confirmed example to intent_examples for future few-shot learning."""
    record = build_example_record(
        pg_id=pg_id, message=message, intent=intent, role=role,
        entities=entities, confidence=confidence, source=source, confirmed_by=confirmed_by,
    )
    try:
        await session.execute(insert(IntentExample).values(**record))
        await session.commit()
        logger.info(
            f"[LearningAgent] Saved example: '{message[:50]}' -> {intent} "
            f"(source={source}, pg={pg_id[:8]})"
        )
    except Exception as e:
        logger.error(f"[LearningAgent] Failed to save example: {e}")
        await session.rollback()


async def learn_from_interaction(
    pg_id: str,
    message: str,
    phone: str,
    role: str,
    regex_result: Optional[str],
    regex_confidence: Optional[float],
    llm_result: Optional[str],
    llm_confidence: Optional[float],
    final_intent: str,
    entities: dict,  # session arg is ignored — we open our own to avoid racing main handler's commit
    source: str,
    session: AsyncSession,
) -> None:
    """
    Main entry point — called after every LLM classification.
    Logs the classification and saves examples when appropriate.
    Runs as fire-and-forget background task (non-blocking).

    Opens its OWN session to avoid racing the main handler's commit
    (previous design shared the caller's session, which caused
    ResourceClosedError when the main handler committed while this
    task was mid-flush).
    """
    from src.database.db_manager import get_session
    async with get_session() as own_session:
        try:
            await log_classification(
                pg_id=pg_id, message=message, phone=phone, role=role,
                regex_result=regex_result, regex_confidence=regex_confidence,
                llm_result=llm_result, llm_confidence=llm_confidence,
                final_intent=final_intent, session=own_session,
            )

            if source in ("user_correction", "user_selection", "user_clarification", "manual_teach"):
                await save_example(
                    pg_id=pg_id, message=message, intent=final_intent, role=role,
                    entities=entities, confidence=llm_confidence or 0.0,
                    source=source, confirmed_by=phone, session=own_session,
                )
            elif source == "auto_confirmed" and should_auto_confirm(llm_confidence or 0.0, was_corrected=False):
                await save_example(
                    pg_id=pg_id, message=message, intent=final_intent, role=role,
                    entities=entities, confidence=llm_confidence or 0.0,
                    source="auto_confirmed", confirmed_by="system", session=own_session,
                )
        except Exception as e:
            logger.error(f"[LearningAgent] learn_from_interaction failed: {e}")
