"""
Anonymized, duration-weighted feedback summary for an instructor.

Algorithm:
1. Take the instructor's last 10 completed sessions (by scheduled_date,
   across all their classes).
2. For each of those sessions that has feedback, compute the mean of
   each rating dimension over that session's feedback entries.
3. Weight each session's means by its duration_minutes (read from
   session_metadata) and combine:
       weighted_avg = sum(duration_i * mean_i) / sum(duration_i)
   Sessions with no feedback carry no score, so they contribute no
   weight. Sessions with a missing/invalid duration are skipped rather
   than guessed at.
4. `overall` is the same weighted average over each session's mean of
   the three dimensions.

Only aggregates are returned. If fewer than MIN_STUDENTS distinct
students contributed, the scores are withheld (null) so a single
student's ratings can't be read straight off the card.
"""

from django.db.models import Avg, Count

from classes.models import Session
from .models import SessionFeedback


WINDOW_SIZE = 10
MIN_STUDENTS = 3
DIMENSIONS = ("clarity", "engagement", "pace")


def _duration(session):
    value = session.session_metadata.get("duration_minutes")
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        return None
    return value


def build_instructor_summary(instructor):
    sessions = list(
        Session.objects.filter(
            class_obj__instructor=instructor,
            status=Session.Status.COMPLETED,
        ).order_by("-scheduled_date")[:WINDOW_SIZE]
    )
    durations = {s.id: _duration(s) for s in sessions}
    weighted_ids = [sid for sid, d in durations.items() if d is not None]

    feedback = SessionFeedback.objects.filter(session_id__in=weighted_ids)
    per_session = feedback.order_by().values("session_id").annotate(
        clarity=Avg("rating_clarity"),
        engagement=Avg("rating_engagement"),
        pace=Avg("rating_pace"),
        entries=Count("id"),
    )
    distinct_students = feedback.values("student_id").distinct().count()

    total_weight = 0
    weighted_sums = {dim: 0.0 for dim in DIMENSIONS + ("overall",)}
    total_feedback = 0
    for row in per_session:
        weight = durations[row["session_id"]]
        total_weight += weight
        total_feedback += row["entries"]
        session_overall = sum(row[dim] for dim in DIMENSIONS) / len(DIMENSIONS)
        for dim in DIMENSIONS:
            weighted_sums[dim] += weight * row[dim]
        weighted_sums["overall"] += weight * session_overall

    meets_threshold = distinct_students >= MIN_STUDENTS
    if total_weight and meets_threshold:
        averages = {
            key: round(value / total_weight, 2)
            for key, value in weighted_sums.items()
        }
    else:
        averages = {key: None for key in weighted_sums}

    return {
        "instructor_id": instructor.id,
        "window_size": WINDOW_SIZE,
        "sessions_in_window": len(sessions),
        "sessions_with_feedback": len(per_session),
        "total_feedback": total_feedback,
        "meets_anonymity_threshold": meets_threshold,
        "min_students_required": MIN_STUDENTS,
        "weighted_averages": averages,
    }
