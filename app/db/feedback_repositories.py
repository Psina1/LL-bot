from __future__ import annotations

from datetime import datetime

from sqlalchemy import and_, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    AllowedUser,
    FeedbackCampaign,
    FeedbackDelivery,
    FeedbackResponse,
    ProgramLesson,
    User,
    UserNotificationSetting,
)


class FeedbackCampaignRepository:
    @staticmethod
    async def create(
        session: AsyncSession,
        lesson: ProgramLesson,
        created_by_user_id: int,
        launch_at: datetime,
        is_test: bool,
        initial_text_override: str | None = None,
        reminder_text_override: str | None = None,
        usefulness_question: str | None = None,
        experts_question: str | None = None,
        valuable_question: str | None = None,
        improvement_question: str | None = None,
    ) -> FeedbackCampaign:
        campaign = FeedbackCampaign(
            lesson_id=lesson.id,
            lesson_key=lesson.lesson_key,
            lesson_title=lesson.lesson_title,
            lesson_date=lesson.date_start,
            experts=lesson.speaker,
            initial_text_override=initial_text_override,
            reminder_text_override=reminder_text_override,
            usefulness_question=usefulness_question,
            experts_question=experts_question,
            valuable_question=valuable_question,
            improvement_question=improvement_question,
            status="scheduled",
            is_test=is_test,
            launch_at=launch_at,
            created_by_user_id=created_by_user_id,
        )
        session.add(campaign)
        await session.commit()
        await session.refresh(campaign)
        return campaign

    @staticmethod
    async def get(session: AsyncSession, campaign_id: int) -> FeedbackCampaign | None:
        result = await session.execute(
            select(FeedbackCampaign).where(FeedbackCampaign.id == campaign_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def list_due(session: AsyncSession, now: datetime) -> list[FeedbackCampaign]:
        result = await session.execute(
            select(FeedbackCampaign)
            .where(
                and_(
                    FeedbackCampaign.status == "scheduled",
                    FeedbackCampaign.launch_at.is_not(None),
                    FeedbackCampaign.launch_at <= now,
                )
            )
            .order_by(FeedbackCampaign.launch_at.asc())
        )
        return list(result.scalars().all())

    @staticmethod
    async def list_recent(session: AsyncSession, limit: int = 10) -> list[FeedbackCampaign]:
        result = await session.execute(
            select(FeedbackCampaign)
            .order_by(FeedbackCampaign.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    @staticmethod
    async def mark_active(session: AsyncSession, campaign_id: int) -> None:
        campaign = await FeedbackCampaignRepository.get(session, campaign_id)
        if campaign is None:
            return
        campaign.status = "active"
        await session.commit()

    @staticmethod
    async def close(session: AsyncSession, campaign_id: int, now: datetime) -> None:
        campaign = await FeedbackCampaignRepository.get(session, campaign_id)
        if campaign is None:
            return
        campaign.status = "closed"
        campaign.closed_at = now
        await session.commit()


class FeedbackResponseRepository:
    @staticmethod
    async def ensure_for_user(
        session: AsyncSession,
        campaign_id: int,
        user_id: int,
    ) -> FeedbackResponse:
        stmt = pg_insert(FeedbackResponse).values(
            campaign_id=campaign_id,
            user_id=user_id,
            status="pending",
            current_step="invitation",
        )
        stmt = stmt.on_conflict_do_nothing(
            constraint="uq_feedback_response_campaign_user"
        ).returning(FeedbackResponse.id)
        inserted_id = (await session.execute(stmt)).scalar_one_or_none()
        await session.commit()

        if inserted_id is not None:
            response = await session.get(FeedbackResponse, inserted_id)
            if response is not None:
                return response

        result = await session.execute(
            select(FeedbackResponse).where(
                and_(
                    FeedbackResponse.campaign_id == campaign_id,
                    FeedbackResponse.user_id == user_id,
                )
            )
        )
        return result.scalar_one()

    @staticmethod
    async def get(session: AsyncSession, response_id: int) -> FeedbackResponse | None:
        return await session.get(FeedbackResponse, response_id)

    @staticmethod
    async def get_for_user(
        session: AsyncSession,
        response_id: int,
        user_id: int,
    ) -> FeedbackResponse | None:
        result = await session.execute(
            select(FeedbackResponse).where(
                and_(
                    FeedbackResponse.id == response_id,
                    FeedbackResponse.user_id == user_id,
                )
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_open_answer_for_telegram_user(
        session: AsyncSession,
        telegram_id: int,
    ) -> FeedbackResponse | None:
        result = await session.execute(
            select(FeedbackResponse)
            .join(User, User.id == FeedbackResponse.user_id)
            .join(FeedbackCampaign, FeedbackCampaign.id == FeedbackResponse.campaign_id)
            .where(
                and_(
                    User.telegram_id == telegram_id,
                    FeedbackCampaign.status == "active",
                    FeedbackResponse.status == "in_progress",
                    FeedbackResponse.current_step.in_(["valuable", "improvement"]),
                )
            )
            .order_by(FeedbackResponse.updated_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def mark_initial_sent(
        session: AsyncSession,
        response_id: int,
        sent_at: datetime,
        next_reminder_at: datetime,
    ) -> None:
        response = await FeedbackResponseRepository.get(session, response_id)
        if response is None:
            return
        response.initial_sent_at = sent_at
        response.next_reminder_at = next_reminder_at
        await session.commit()

    @staticmethod
    async def start(session: AsyncSession, response_id: int, now: datetime) -> None:
        response = await FeedbackResponseRepository.get(session, response_id)
        if response is None:
            return
        response.status = "in_progress"
        response.current_step = "usefulness"
        response.started_at = response.started_at or now
        await session.commit()

    @staticmethod
    async def set_terminal_status(
        session: AsyncSession,
        response_id: int,
        status: str,
        now: datetime,
    ) -> None:
        response = await FeedbackResponseRepository.get(session, response_id)
        if response is None:
            return
        response.status = status
        response.current_step = "finished"
        response.next_reminder_at = None
        response.completed_at = now
        await session.commit()

    @staticmethod
    async def set_usefulness_score(
        session: AsyncSession,
        response_id: int,
        score: int,
    ) -> None:
        response = await FeedbackResponseRepository.get(session, response_id)
        if response is None:
            return
        response.usefulness_score = score
        response.status = "in_progress"
        response.current_step = "experts"
        await session.commit()

    @staticmethod
    async def set_experts_score(
        session: AsyncSession,
        response_id: int,
        score: int,
    ) -> None:
        response = await FeedbackResponseRepository.get(session, response_id)
        if response is None:
            return
        response.experts_score = score
        response.current_step = "valuable"
        await session.commit()

    @staticmethod
    async def set_valuable_answer(
        session: AsyncSession,
        response_id: int,
        answer: str,
        input_type: str,
        voice_file_id: str | None = None,
        transcription_model: str | None = None,
    ) -> None:
        response = await FeedbackResponseRepository.get(session, response_id)
        if response is None:
            return
        response.valuable_answer = answer.strip()
        response.valuable_input_type = input_type
        response.valuable_voice_file_id = voice_file_id
        response.valuable_transcription_model = transcription_model
        response.current_step = "improvement"
        await session.commit()

    @staticmethod
    async def set_improvement_answer(
        session: AsyncSession,
        response_id: int,
        answer: str,
        input_type: str,
        now: datetime,
        voice_file_id: str | None = None,
        transcription_model: str | None = None,
    ) -> None:
        response = await FeedbackResponseRepository.get(session, response_id)
        if response is None:
            return
        response.improvement_answer = answer.strip()
        response.improvement_input_type = input_type
        response.improvement_voice_file_id = voice_file_id
        response.improvement_transcription_model = transcription_model
        response.status = "completed"
        response.current_step = "finished"
        response.next_reminder_at = None
        response.completed_at = now
        await session.commit()

    @staticmethod
    async def postpone(
        session: AsyncSession,
        response_id: int,
        next_reminder_at: datetime,
    ) -> None:
        response = await FeedbackResponseRepository.get(session, response_id)
        if response is None:
            return
        if response.status not in {"completed", "not_attended", "declined"}:
            response.next_reminder_at = next_reminder_at
        await session.commit()

    @staticmethod
    async def list_due_reminders(
        session: AsyncSession,
        now: datetime,
        limit: int = 100,
    ) -> list[tuple[FeedbackResponse, FeedbackCampaign, User, str | None]]:
        result = await session.execute(
            select(
                FeedbackResponse,
                FeedbackCampaign,
                User,
                UserNotificationSetting.notification_time,
            )
            .join(FeedbackCampaign, FeedbackCampaign.id == FeedbackResponse.campaign_id)
            .join(User, User.id == FeedbackResponse.user_id)
            .outerjoin(
                UserNotificationSetting,
                UserNotificationSetting.user_id == User.id,
            )
            .where(
                and_(
                    FeedbackCampaign.status == "active",
                    FeedbackResponse.status.in_(["pending", "in_progress"]),
                    FeedbackResponse.reminder_count < 2,
                    FeedbackResponse.next_reminder_at.is_not(None),
                    FeedbackResponse.next_reminder_at <= now,
                )
            )
            .order_by(FeedbackResponse.next_reminder_at.asc())
            .limit(limit)
        )
        return list(result.all())

    @staticmethod
    async def mark_reminder_sent(
        session: AsyncSession,
        response_id: int,
        sent_at: datetime,
        next_reminder_at: datetime | None,
    ) -> None:
        response = await FeedbackResponseRepository.get(session, response_id)
        if response is None:
            return
        response.reminder_count += 1
        response.last_reminder_at = sent_at
        response.next_reminder_at = next_reminder_at
        await session.commit()

    @staticmethod
    async def list_export_rows(
        session: AsyncSession,
        campaign_id: int,
    ) -> list[tuple[FeedbackResponse, FeedbackCampaign, User, AllowedUser | None]]:
        result = await session.execute(
            select(FeedbackResponse, FeedbackCampaign, User, AllowedUser)
            .join(FeedbackCampaign, FeedbackCampaign.id == FeedbackResponse.campaign_id)
            .join(User, User.id == FeedbackResponse.user_id)
            .outerjoin(AllowedUser, AllowedUser.telegram_id == User.telegram_id)
            .where(FeedbackResponse.campaign_id == campaign_id)
            .order_by(
                AllowedUser.full_name.asc().nulls_last(),
                User.full_name.asc().nulls_last(),
                User.username.asc().nulls_last(),
                User.telegram_id.asc(),
            )
        )
        return list(result.all())

    @staticmethod
    async def campaign_totals(
        session: AsyncSession,
        campaign_id: int,
    ) -> dict[str, int]:
        result = await session.execute(
            select(FeedbackResponse.status, func.count(FeedbackResponse.id))
            .where(FeedbackResponse.campaign_id == campaign_id)
            .group_by(FeedbackResponse.status)
        )
        return {str(status): int(count) for status, count in result.all()}


class FeedbackDeliveryRepository:
    @staticmethod
    async def was_sent(
        session: AsyncSession,
        response_id: int,
        delivery_type: str,
    ) -> bool:
        result = await session.execute(
            select(FeedbackDelivery.status).where(
                and_(
                    FeedbackDelivery.response_id == response_id,
                    FeedbackDelivery.delivery_type == delivery_type,
                )
            )
        )
        return result.scalar_one_or_none() == "sent"

    @staticmethod
    async def mark(
        session: AsyncSession,
        campaign_id: int,
        response_id: int,
        user_id: int,
        delivery_type: str,
        scheduled_at: datetime,
        status: str,
        sent_at: datetime | None = None,
        error_text: str | None = None,
    ) -> None:
        stmt = pg_insert(FeedbackDelivery).values(
            campaign_id=campaign_id,
            response_id=response_id,
            user_id=user_id,
            delivery_type=delivery_type,
            scheduled_at=scheduled_at,
            sent_at=sent_at,
            status=status,
            error_text=error_text[:10000] if error_text else None,
        )
        stmt = stmt.on_conflict_do_update(
            constraint="uq_feedback_delivery_response_type",
            set_={
                "scheduled_at": scheduled_at,
                "sent_at": sent_at,
                "status": status,
                "error_text": error_text[:10000] if error_text else None,
            },
        )
        await session.execute(stmt)
        await session.commit()


async def list_feedback_recipients(
    session: AsyncSession,
    admin_ids: list[int],
    is_test: bool,
) -> list[tuple[User, str | None]]:
    admin_filter = User.telegram_id.in_(admin_ids)
    query = (
        select(User, UserNotificationSetting.notification_time)
        .outerjoin(UserNotificationSetting, UserNotificationSetting.user_id == User.id)
        .order_by(User.id.asc())
    )
    if is_test:
        query = query.where(admin_filter)
    else:
        query = (
            query.join(AllowedUser, AllowedUser.telegram_id == User.telegram_id)
            .where(
                ~admin_filter,
                AllowedUser.is_active.is_(True),
            )
        )
    result = await session.execute(query)
    return list(result.all())
