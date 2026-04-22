from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from django.utils import timezone

from apps.scouting.models import Patrol, PatrolYouTubeSubmission, PointLog


@dataclass(frozen=True)
class PoentaroSnapshot:
    base_points: int
    daily_telegram_points: int
    peer_validation_points: int
    leader_multiplier: float
    effective_score: int
    mcer_level: str


class PoentaroEngine:
    """
    Combines core score components for progression:
    1) daily Telegram participation bonus (all members participated),
    2) peer validation anonymous vote average,
    3) leader "Siempre Listo" multiplier.
    
    Definitive MCER thresholds (SEL Sprint 3):
    - A1 Malkovranto: 0-1,000 pts
    - A2 Vojtrovanto: 1,001-3,000 pts
    - B1 Esploristo: 3,001-6,000 pts
    - B2 Gvidanto: 6,001+ pts
    """

    DAILY_TELEGRAM_TEAM_POINTS = 30
    THRESHOLD_A1 = 1000
    THRESHOLD_A2 = 3000
    THRESHOLD_B1 = 6000

    def compute(self, patrol: Patrol) -> PoentaroSnapshot:
        base_points = int(patrol.sel_points)
        daily_telegram_points = self._daily_telegram_points(patrol)
        peer_validation_points = self._peer_validation_points(patrol)
        leader_multiplier = self._leader_multiplier(patrol)

        effective_score = int(
            round((base_points + daily_telegram_points + peer_validation_points) * leader_multiplier)
        )

        if effective_score >= self.THRESHOLD_B1:
            mcer_level = "B2"
        elif effective_score >= self.THRESHOLD_A2:
            mcer_level = "B1"
        elif effective_score >= self.THRESHOLD_A1:
            mcer_level = "A2"
        else:
            mcer_level = "A1"

        return PoentaroSnapshot(
            base_points=base_points,
            daily_telegram_points=daily_telegram_points,
            peer_validation_points=peer_validation_points,
            leader_multiplier=leader_multiplier,
            effective_score=effective_score,
            mcer_level=mcer_level,
        )

    def _daily_telegram_points(self, patrol: Patrol) -> int:
        now = timezone.now()
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

        daily_logs = PointLog.objects.filter(
            patrol=patrol,
            event_type__in=[PointLog.EventType.TEXT_VALIDATED, PointLog.EventType.AUDIO_VALIDATED],
            created_at__gte=day_start,
        )

        if not daily_logs.exists():
            return 0

        participant_tokens: set[str] = set()
        for log in daily_logs:
            meta = log.metadata or {}
            token = (
                str(meta.get("participant_id") or "").strip()
                or str(meta.get("scout_id") or "").strip()
                or str(meta.get("sender") or "").strip()
            )
            if token:
                participant_tokens.add(token)

        all_participated = False
        if participant_tokens:
            all_participated = len(participant_tokens) >= patrol.member_count
        else:
            # Fallback when member ids are not yet instrumented.
            all_participated = daily_logs.count() >= patrol.member_count

        return self.DAILY_TELEGRAM_TEAM_POINTS if all_participated else 0

    def _peer_validation_points(self, patrol: Patrol) -> int:
        window_start = timezone.now() - timedelta(days=14)
        logs = PointLog.objects.filter(patrol=patrol, created_at__gte=window_start)

        votes: list[float] = []
        for log in logs:
            meta = log.metadata or {}
            if not bool(meta.get("anonymous_vote", False)):
                continue
            raw_vote = meta.get("peer_vote")
            try:
                vote = float(raw_vote)
            except (TypeError, ValueError):
                continue
            if 0 <= vote <= 5:
                votes.append(vote)

        if not votes:
            return 0

        avg_vote = sum(votes) / len(votes)
        # Scale 0..5 into 0..100 points.
        return int(round(avg_vote * 20))

    def _leader_multiplier(self, patrol: Patrol) -> float:
        submission = PatrolYouTubeSubmission.objects.filter(patrol=patrol).first()
        if not submission:
            return 1.0

        if (
            submission.leader_approval_status
            == PatrolYouTubeSubmission.LeaderApprovalStatus.APPROVED
        ):
            return 1.15

        return 1.0
