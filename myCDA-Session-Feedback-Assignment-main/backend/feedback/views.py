from rest_framework import generics
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.generics import get_object_or_404
from rest_framework.response import Response
from rest_framework.views import APIView

from core.permissions import IsInstructorOrAdmin, IsStudentOrParent
from accounts.models import FamilyLink, User
from classes.serializers import SessionSerializer
from .models import SessionFeedback, eligible_sessions_for
from .serializers import InstructorSummarySerializer, SessionFeedbackSerializer
from .summary import build_instructor_summary


class FeedbackCreateView(generics.CreateAPIView):
    """POST feedback for a session (student for self, parent for a linked student)."""

    serializer_class = SessionFeedbackSerializer
    permission_classes = [IsStudentOrParent]


class MyFeedbackListView(generics.ListAPIView):
    """
    List feedback about the current student, or about any of a parent's
    linked students. Most recent first.
    """

    serializer_class = SessionFeedbackSerializer
    permission_classes = [IsStudentOrParent]

    def get_queryset(self):
        user = self.request.user
        if user.role == "student":
            queryset = SessionFeedback.objects.filter(student=user)
        else:
            children = FamilyLink.objects.filter(
                parent=user
            ).values_list("student_id", flat=True)
            queryset = SessionFeedback.objects.filter(student__in=children)
        return queryset.select_related(
            "session", "session__class_obj", "session__class_obj__instructor",
            "student", "created_by",
        ).order_by("-created_at")


class EligibleSessionsView(generics.ListAPIView):
    """
    List sessions a student can still review. Students get their own;
    parents pass `?student=<id>` for one of their linked students.
    """

    serializer_class = SessionSerializer
    permission_classes = [IsStudentOrParent]

    def get_queryset(self):
        user = self.request.user
        if user.role == "student":
            return eligible_sessions_for(user)

        student_id = self.request.query_params.get("student")
        if not student_id:
            raise ValidationError({"student": "This query parameter is required for parents."})
        link = FamilyLink.objects.filter(
            parent=user, student_id=student_id
        ).select_related("student").first()
        if link is None:
            raise PermissionDenied("You can only view sessions for your linked students.")
        return eligible_sessions_for(link.student)


class InstructorSummaryView(APIView):
    """
    GET the anonymized, duration-weighted rolling average for an
    instructor. Instructors always get their own summary; admins must
    pass `?instructor_id=<id>`.
    """

    permission_classes = [IsInstructorOrAdmin]

    def get(self, request):
        if request.user.role == "instructor":
            instructor = request.user
        else:
            instructor_id = request.query_params.get("instructor_id")
            if not instructor_id or not instructor_id.isdigit():
                raise ValidationError({"instructor_id": "A valid instructor_id is required."})
            instructor = get_object_or_404(
                User, pk=instructor_id, role=User.Role.INSTRUCTOR
            )

        summary = build_instructor_summary(instructor)
        return Response(InstructorSummarySerializer(summary).data)
