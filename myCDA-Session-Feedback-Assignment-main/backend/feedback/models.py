from datetime import timedelta

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

from accounts.models import User
from classes.models import Session


RATING_VALIDATORS = [MinValueValidator(1), MaxValueValidator(5)]

# Feedback is accepted for this many days after a session took place.
FEEDBACK_WINDOW_DAYS = 30


def feedback_window_start():
    return timezone.now() - timedelta(days=FEEDBACK_WINDOW_DAYS)


def eligible_sessions_for(student):
    """
    Sessions `student` can still leave feedback for: completed, inside
    the 30-day window, in a class they're actively enrolled in, and not
    already reviewed for this student.
    """
    return (
        Session.objects.filter(
            status=Session.Status.COMPLETED,
            scheduled_date__gte=feedback_window_start(),
            class_obj__enrollments__student=student,
            class_obj__enrollments__is_active=True,
        )
        .exclude(feedback__student=student)
        .select_related("class_obj", "class_obj__instructor")
        .distinct()
    )


class SessionFeedback(models.Model):
    """
    A structured review of a completed session, left by a student or by
    a parent on behalf of a linked student.

    `student` is who the feedback represents; `created_by` is who
    actually submitted it (the student themselves or a linked parent).
    The submitter is stored as `created_by` so BaseModelSerializer
    auto-populates it from the request user.

    Uniqueness is on (session, student): a student gets one review per
    session no matter who submits it.
    """

    session = models.ForeignKey(
        Session,
        on_delete=models.CASCADE,
        related_name="feedback",
    )
    student = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="session_feedback",
        limit_choices_to={"role": "student"},
    )
    created_by = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="submitted_feedback",
        verbose_name="submitter",
    )
    rating_clarity = models.PositiveSmallIntegerField(
        validators=RATING_VALIDATORS,
        help_text="How clearly the instructor explained concepts (1-5).",
    )
    rating_engagement = models.PositiveSmallIntegerField(
        validators=RATING_VALIDATORS,
        help_text="How engaging the session was (1-5).",
    )
    rating_pace = models.PositiveSmallIntegerField(
        validators=RATING_VALIDATORS,
        help_text="Whether the pacing felt right (1-5).",
    )
    note = models.TextField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        unique_together = ("session", "student")
        constraints = [
            models.CheckConstraint(
                condition=models.Q(rating_clarity__gte=1, rating_clarity__lte=5)
                & models.Q(rating_engagement__gte=1, rating_engagement__lte=5)
                & models.Q(rating_pace__gte=1, rating_pace__lte=5),
                name="feedback_ratings_between_1_and_5",
            ),
        ]
        verbose_name = "session feedback"
        verbose_name_plural = "session feedback"

    def __str__(self):
        return f"Feedback for {self.session} ({self.student.get_display_name()})"
