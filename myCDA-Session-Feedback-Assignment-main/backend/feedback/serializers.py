from django.db import IntegrityError, transaction
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied

from core.middleware import get_current_user
from core.serializers import BaseModelSerializer
from accounts.models import FamilyLink, User
from accounts.serializers import UserMinimalSerializer
from classes.models import ClassEnrollment, Session
from classes.serializers import SessionSerializer
from .models import SessionFeedback, feedback_window_start


DUPLICATE_MESSAGE = "Feedback already submitted for this session."


class SessionFeedbackSerializer(BaseModelSerializer):
    """
    Student/parent-facing feedback serializer (submit + history).

    `created_by` (the submitter) is never accepted from the request
    body -- BaseModelSerializer.create() fills it from the request user.
    `student` is optional for students (defaults to themselves) and
    required for parents.

    NOT for instructor-facing responses: it exposes the student and the
    note. Instructors only ever get InstructorSummarySerializer.
    """

    student = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.filter(role=User.Role.STUDENT),
        required=False,
    )
    session_display = SessionSerializer(source="session", read_only=True)
    student_display = UserMinimalSerializer(source="student", read_only=True)

    class Meta:
        model = SessionFeedback
        fields = [
            "id",
            "session",
            "session_display",
            "student",
            "student_display",
            "rating_clarity",
            "rating_engagement",
            "rating_pace",
            "note",
            "created_by_display",
            "created_at",
            "updated_at",
        ]
        # Uniqueness on (session, student) is checked in validate() so
        # `student` can stay optional and the error message is friendly.
        validators = []

    def validate(self, data):
        user = get_current_user()
        session = data["session"]
        student = self._resolve_student(user, data.get("student"))

        if session.status != Session.Status.COMPLETED:
            raise serializers.ValidationError(
                {"session": "Feedback can only be left for completed sessions."}
            )
        if session.scheduled_date < feedback_window_start():
            raise serializers.ValidationError(
                {"session": "The feedback window for this session has closed (30 days)."}
            )
        if not ClassEnrollment.objects.filter(
            class_obj=session.class_obj, student=student, is_active=True
        ).exists():
            raise serializers.ValidationError(
                {"session": "This student is not enrolled in this session's class."}
            )
        if SessionFeedback.objects.filter(session=session, student=student).exists():
            raise serializers.ValidationError({"session": DUPLICATE_MESSAGE})

        data["student"] = student
        return data

    def _resolve_student(self, user, student):
        """Students submit for themselves; parents for a linked student."""
        if user.role == User.Role.STUDENT:
            if student is not None and student != user:
                raise PermissionDenied("Students can only submit feedback for themselves.")
            return user

        if user.role == User.Role.PARENT:
            if student is None:
                raise serializers.ValidationError(
                    {"student": "Select which student this feedback is for."}
                )
            if not FamilyLink.objects.filter(parent=user, student=student).exists():
                raise PermissionDenied("You can only submit feedback for your linked students.")
            return student

        raise PermissionDenied("Only students and parents can submit feedback.")

    def create(self, validated_data):
        # The DB constraint is the final guard against a concurrent
        # duplicate slipping past validate().
        try:
            with transaction.atomic():
                return super().create(validated_data)
        except IntegrityError:
            raise serializers.ValidationError({"session": DUPLICATE_MESSAGE})


class DimensionScoresSerializer(serializers.Serializer):
    clarity = serializers.FloatField(allow_null=True)
    engagement = serializers.FloatField(allow_null=True)
    pace = serializers.FloatField(allow_null=True)
    overall = serializers.FloatField(allow_null=True)


class InstructorSummarySerializer(serializers.Serializer):
    """
    Instructor-facing aggregate. Deliberately a plain Serializer over a
    dict rather than a ModelSerializer over SessionFeedback: the only
    fields that can ever leave this endpoint are the ones declared here,
    and none of them identify a student, a submitter, or carry a note.
    """

    instructor_id = serializers.IntegerField()
    window_size = serializers.IntegerField()
    sessions_in_window = serializers.IntegerField()
    sessions_with_feedback = serializers.IntegerField()
    total_feedback = serializers.IntegerField()
    meets_anonymity_threshold = serializers.BooleanField()
    min_students_required = serializers.IntegerField()
    weighted_averages = DimensionScoresSerializer()
