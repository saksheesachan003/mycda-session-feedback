from datetime import timedelta

from django.test import TestCase as DjangoTestCase, override_settings
from django.utils import timezone
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from accounts.models import FamilyLink, User
from classes.models import Class, ClassEnrollment, Session
from feedback.models import SessionFeedback


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class TestCase(DjangoTestCase):
    """Fast password hashing -- these tests create many users."""


RATINGS = {"rating_clarity": 4, "rating_engagement": 5, "rating_pace": 3}


def make_user(username, role, **kwargs):
    return User.objects.create_user(
        username=username, email=f"{username}@cda.test",
        password="testpass123", role=role, **kwargs,
    )


def make_session(cls, days_ago=3, status="completed", duration=60):
    return Session.objects.create(
        class_obj=cls,
        scheduled_date=timezone.now() - timedelta(days=days_ago),
        status=status,
        session_metadata={"duration_minutes": duration, "topic_covered": "Topic"},
    )


class FeedbackTestBase(TestCase):
    def setUp(self):
        self.instructor = make_user("instr", "instructor")
        self.student = make_user("stud", "student", first_name="Sam", last_name="Student")
        self.sibling = make_user("sib", "student")
        self.stranger = make_user("stranger", "student")
        self.parent = make_user("parent", "parent")
        self.other_parent = make_user("otherparent", "parent")
        FamilyLink.objects.create(parent=self.parent, student=self.student)
        FamilyLink.objects.create(parent=self.parent, student=self.sibling)

        self.cls = Class.objects.create(name="LD", instructor=self.instructor)
        for s in (self.student, self.sibling):
            ClassEnrollment.objects.create(class_obj=self.cls, student=s)
        self.session = make_session(self.cls)

    def client_for(self, user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    def submit(self, user, **extra):
        body = {"session": self.session.id, **RATINGS, **extra}
        return self.client_for(user).post("/api/v1/feedback/", body, format="json")


class SubmitFeedbackTests(FeedbackTestBase):
    def test_student_submits_for_self_with_token_auth(self):
        """Token auth path: submitter must come from the authenticated user."""
        client = APIClient()
        token = Token.objects.create(user=self.student)
        client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")
        response = client.post(
            "/api/v1/feedback/", {"session": self.session.id, **RATINGS}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        feedback = SessionFeedback.objects.get()
        self.assertEqual(feedback.student, self.student)
        self.assertEqual(feedback.created_by, self.student)

    def test_submitter_in_body_is_ignored(self):
        response = self.submit(self.student, created_by=self.parent.id)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(SessionFeedback.objects.get().created_by, self.student)

    def test_parent_submits_for_linked_student(self):
        response = self.submit(self.parent, student=self.sibling.id)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        feedback = SessionFeedback.objects.get()
        self.assertEqual(feedback.student, self.sibling)
        self.assertEqual(feedback.created_by, self.parent)

    def test_parent_must_choose_student(self):
        response = self.submit(self.parent)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("student", response.data)

    def test_parent_cannot_submit_for_unlinked_student(self):
        response = self.submit(self.other_parent, student=self.student.id)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_student_cannot_submit_for_someone_else(self):
        response = self.submit(self.student, student=self.sibling.id)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_instructor_cannot_submit(self):
        response = self.submit(self.instructor)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_rejects_non_completed_sessions(self):
        for session_status in ("scheduled", "cancelled"):
            session = make_session(self.cls, status=session_status)
            response = self.submit(self.student, session=session.id)
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_rejects_sessions_older_than_30_days(self):
        old = make_session(self.cls, days_ago=31)
        response = self.submit(self.student, session=old.id)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_rejects_student_not_enrolled(self):
        response = self.submit(self.stranger)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_rejects_out_of_range_ratings(self):
        for bad in (0, 6):
            response = self.submit(self.student, rating_clarity=bad)
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
            self.assertIn("rating_clarity", response.data)

    def test_rejects_note_over_500_chars(self):
        response = self.submit(self.student, note="x" * 501)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_duplicate_is_per_student_not_per_submitter(self):
        self.assertEqual(self.submit(self.student).status_code, status.HTTP_201_CREATED)
        response = self.submit(self.parent, student=self.student.id)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data["session"][0], "Feedback already submitted for this session."
        )
        # A different student on the same session is fine.
        response = self.submit(self.parent, student=self.sibling.id)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)


class MyFeedbackAndEligibilityTests(FeedbackTestBase):
    def test_parent_sees_feedback_for_all_linked_students(self):
        self.submit(self.student)
        self.submit(self.parent, student=self.sibling.id)
        response = self.client_for(self.parent).get("/api/v1/feedback/my/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 2)

    def test_student_sees_only_own_feedback(self):
        self.submit(self.student)
        self.submit(self.parent, student=self.sibling.id)
        response = self.client_for(self.student).get("/api/v1/feedback/my/")
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["student"], self.student.id)

    def test_eligible_sessions_exclude_reviewed_and_ineligible(self):
        make_session(self.cls, status="cancelled")
        make_session(self.cls, days_ago=40)
        client = self.client_for(self.student)
        response = client.get("/api/v1/feedback/eligible-sessions/")
        self.assertEqual([s["id"] for s in response.data["results"]], [self.session.id])

        self.submit(self.student)
        response = client.get("/api/v1/feedback/eligible-sessions/")
        self.assertEqual(response.data["count"], 0)

    def test_parent_eligible_sessions_require_linked_student(self):
        client = self.client_for(self.parent)
        self.assertEqual(
            client.get("/api/v1/feedback/eligible-sessions/").status_code,
            status.HTTP_400_BAD_REQUEST,
        )
        self.assertEqual(
            client.get(
                f"/api/v1/feedback/eligible-sessions/?student={self.stranger.id}"
            ).status_code,
            status.HTTP_403_FORBIDDEN,
        )
        response = client.get(f"/api/v1/feedback/eligible-sessions/?student={self.sibling.id}")
        self.assertEqual(response.data["count"], 1)


class InstructorSummaryTests(TestCase):
    URL = "/api/v1/feedback/instructor-summary/"

    def setUp(self):
        self.instructor = make_user("instr", "instructor")
        self.other_instructor = make_user("instr2", "instructor")
        self.admin = make_user("admin", "admin")
        self.students = [make_user(f"s{i}", "student") for i in range(3)]
        self.cls = Class.objects.create(name="LD", instructor=self.instructor)

    def add_feedback(self, session, student, clarity, engagement, pace, note=""):
        SessionFeedback.objects.create(
            session=session, student=student, created_by=student,
            rating_clarity=clarity, rating_engagement=engagement,
            rating_pace=pace, note=note,
        )

    def get_summary(self, user, query=""):
        client = APIClient()
        client.force_authenticate(user=user)
        return client.get(self.URL + query)

    def test_weighted_by_duration_not_simple_average(self):
        a, b, c = self.students
        long_session = make_session(self.cls, days_ago=2, duration=90)
        short_session = make_session(self.cls, days_ago=1, duration=60)
        # Long session: clarity avg 4.0 (two entries); short: 3.0 (one entry).
        self.add_feedback(long_session, a, 4, 4, 4)
        self.add_feedback(long_session, b, 4, 2, 4)
        self.add_feedback(short_session, c, 3, 3, 3)

        data = self.get_summary(self.instructor).data
        averages = data["weighted_averages"]
        # (90 * 4.0 + 60 * 3.0) / 150 = 3.6, not the simple 3.5
        self.assertEqual(averages["clarity"], 3.6)
        # long engagement avg 3.0 -> (90*3 + 60*3) / 150 = 3.0
        self.assertEqual(averages["engagement"], 3.0)
        # session overall: long (4+3+4)/3, short 3.0
        expected_overall = round((90 * (11 / 3) + 60 * 3.0) / 150, 2)
        self.assertEqual(averages["overall"], expected_overall)
        self.assertEqual(data["total_feedback"], 3)
        self.assertEqual(data["sessions_with_feedback"], 2)

    def test_only_last_ten_completed_sessions_count(self):
        old = make_session(self.cls, days_ago=20, duration=60)
        for student in self.students:
            self.add_feedback(old, student, 1, 1, 1)
        recent = [make_session(self.cls, days_ago=d, duration=60) for d in range(1, 11)]
        make_session(self.cls, days_ago=0, status="cancelled")
        for student in self.students:
            self.add_feedback(recent[0], student, 5, 5, 5)

        data = self.get_summary(self.instructor).data
        self.assertEqual(data["sessions_in_window"], 10)
        self.assertEqual(data["total_feedback"], 3)
        self.assertEqual(data["weighted_averages"]["clarity"], 5.0)

    def test_response_contains_no_identifying_data(self):
        session = make_session(self.cls)
        for student in self.students:
            self.add_feedback(session, student, 4, 4, 4, note="secret note")

        response = self.get_summary(self.instructor)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            set(response.data),
            {
                "instructor_id", "window_size", "sessions_in_window",
                "sessions_with_feedback", "total_feedback",
                "meets_anonymity_threshold", "min_students_required",
                "weighted_averages",
            },
        )
        self.assertEqual(
            set(response.data["weighted_averages"]),
            {"clarity", "engagement", "pace", "overall"},
        )
        body = response.content.decode()
        for leaked in ("secret note", "@cda.test", '"student"', '"note"', "created_by"):
            self.assertNotIn(leaked, body)

    def test_scores_withheld_below_anonymity_threshold(self):
        session = make_session(self.cls)
        self.add_feedback(session, self.students[0], 5, 5, 5)
        data = self.get_summary(self.instructor).data
        self.assertFalse(data["meets_anonymity_threshold"])
        self.assertIsNone(data["weighted_averages"]["clarity"])
        self.assertEqual(data["total_feedback"], 1)

    def test_instructor_only_sees_own_classes(self):
        other_cls = Class.objects.create(name="PF", instructor=self.other_instructor)
        session = make_session(other_cls)
        for student in self.students:
            self.add_feedback(session, student, 5, 5, 5)
        data = self.get_summary(self.instructor, f"?instructor_id={self.other_instructor.id}").data
        self.assertEqual(data["instructor_id"], self.instructor.id)
        self.assertEqual(data["total_feedback"], 0)

    def test_admin_requires_instructor_id(self):
        self.assertEqual(
            self.get_summary(self.admin).status_code, status.HTTP_400_BAD_REQUEST
        )
        response = self.get_summary(self.admin, f"?instructor_id={self.instructor.id}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["instructor_id"], self.instructor.id)
        self.assertEqual(
            self.get_summary(self.admin, f"?instructor_id={self.students[0].id}").status_code,
            status.HTTP_404_NOT_FOUND,
        )

    def test_students_and_parents_are_forbidden(self):
        parent = make_user("p", "parent")
        for user in (self.students[0], parent):
            self.assertEqual(
                self.get_summary(user).status_code, status.HTTP_403_FORBIDDEN
            )
