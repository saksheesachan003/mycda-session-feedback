# Design Decisions — Session Feedback

## Data model (`feedback/models.py`)

`SessionFeedback` has FKs to `Session`, `student` (`limit_choices_to` role=student) and the submitter, three separate `PositiveSmallIntegerField` ratings, an optional `note` (`max_length=500`) and `created_at`/`updated_at`.

- **Student vs submitter are separate FKs.** A parent can submit on a child's behalf, so "who is this about" and "who typed it" differ. Aggregation and uniqueness care about the student, and the audit trail cares about the submitter.
- **The submitter column is named `created_by`** (verbose name "submitter"). That is the field `BaseModelSerializer.create()` auto-populates from `core.middleware.get_current_user()`. The serializer never declares it, so a `created_by` value in the request body is ignored. It uses `on_delete=PROTECT` so audit history can't silently vanish.
- **Three rating columns, not one.** The summary averages each dimension separately, so they have to be stored separately.
- **`unique_together = ("session", "student")`**, matching how `FamilyLink`/`ClassEnrollment` declare uniqueness. It's on student, not submitter: if a student and their parent both review the same session, it's still one student's opinion counted twice.
- Ratings are enforced three times: model validators (1–5), which DRF picks up for 400s; a DB `CheckConstraint`; and the TS form only allowing 1–5.

## Validation (`SessionFeedbackSerializer.validate`)

All rules are server-side, in this order:

1. **Resolve the student.** A student always submits for themselves (sending someone else's id gives 403). A parent must send `student`, and it must be a `FamilyLink` child (otherwise 403).
2. The session is `completed`.
3. `scheduled_date` is within 30 days. `Session` has no separate completion timestamp, so the scheduled date is the best proxy.
4. The student is actively enrolled in the session's class. This isn't in the spec, but without it a student could rate any class.
5. No existing feedback for (session, student), giving a friendly 400: "Feedback already submitted for this session."

DRF's auto-generated `UniqueTogetherValidator` is disabled (`validators = []`), because it would force `student` to be required and students may omit it. The DB constraint is still the final guard: an `IntegrityError` from a race is converted to the same 400.

The eligibility rules live in one place, `eligible_sessions_for(student)`. The `eligible-sessions/` endpoint the form uses calls it, so the list a user sees matches what the API accepts.

## Fix to `core/middleware.py`

While testing I found that `get_current_user()` returned `AnonymousUser` for every token-authenticated request. The middleware captured `request.user` before DRF's `TokenAuthentication` runs (DRF authenticates inside the view, after Django middleware). As a result, `BaseModelSerializer.create()` never set `created_by` for API clients. The middleware now stores the request and reads `request.user` when asked. DRF's `Request.user` setter writes the authenticated user back onto the Django request, so the value is correct by the time a serializer runs. `test_student_submits_for_self_with_token_auth` covers this through real token auth. The fix is in `core` rather than worked around in `perform_create`, because every app that relies on `created_by` has the same bug.

## Endpoints (`feedback/urls.py`)

| Method | Path | Permission |
|---|---|---|
| POST | `/api/v1/feedback/` | `IsStudentOrParent` |
| GET | `/api/v1/feedback/my/` | `IsStudentOrParent` — student: about them; parent: about any linked child. Newest first, `StandardPagination` via settings |
| GET | `/api/v1/feedback/eligible-sessions/` | `IsStudentOrParent` — parents pass `?student=<id>` (must be linked). Reuses `classes.SessionSerializer` |
| GET | `/api/v1/feedback/instructor-summary/` | `IsInstructorOrAdmin` — instructors always get their own; admins must pass `?instructor_id=` |

These are generic views with role-based `get_queryset`, the same pattern as `classes/views.py`.

## Anonymization

This is enforced at the API layer, not the UI:

- **The instructor endpoint has its own serializer**, `InstructorSummarySerializer`. It is a plain `Serializer` over a dict that `feedback/summary.py` builds, not a `ModelSerializer` over `SessionFeedback`. The only keys that can leave the endpoint are the ones declared on it: counts, window info and the four averages. No student, submitter, note or feedback id exists in that code path, so there's nothing to accidentally "add to fields".
- **No per-session breakdown.** Only one number per dimension across the whole window is returned, so an instructor can't match a session score to the one or two students who attended.
- **Minimum-group threshold.** Even a pure aggregate leaks when one student is the only contributor: the average *is* their rating. If fewer than `MIN_STUDENTS = 3` distinct students contributed in the window, the averages are returned as `null` with `meets_anonymity_threshold: false`, and the card explains why. The count is still shown, since "someone left feedback" reveals nothing. A test asserts the raw response body contains none of `student`, `submitter`, `created_by`, `note` or `email`.
- `SessionFeedbackSerializer` does expose `student` and `note`, but only to the student themselves or their linked parents, via `my/`.

## Weighted rolling average (`feedback/summary.py`)

1. Take the instructor's **last 10 `completed` sessions** by `scheduled_date`, across all their classes. Cancelled and scheduled sessions never enter the window.
2. One grouped query computes the per-session mean of each dimension, plus the entry count.
3. Weight each session's mean by `session_metadata["duration_minutes"]`:
   `avg = Σ(duration_i × mean_i) / Σ(duration_i)`, over sessions in the window that have feedback.
4. `overall` is the same weighted average over each session's mean of its three dimension means. Because the weights are the same, this equals the mean of the three weighted dimension averages.

For example, a 90-minute session with average clarity 4.0 and a 60-minute session with 3.0 give **3.6**, not 3.5. This exact case is in the tests.

Choices made here:
- It weights **per-session means**, not individual entries. A session with 3 reviews and one with 1 review count by duration only, as the spec describes ("weight each session's average score").
- Sessions in the window with **no feedback contribute no weight**. They have no score to weight. The window is still "last 10 completed sessions", not "last 10 sessions that happen to have feedback".
- Duration is read **directly from `session_metadata`**. If it's missing or not a positive number, that session is skipped rather than guessed at. `Session.duration_minutes` silently defaults to 60, which would distort a weighted average.

## Frontend

- `StudentFeedbackCards` (students and parents) owns the history state and renders `FeedbackFormCard` and `FeedbackHistoryCard`, both built on `DashboardCard`. Parents pick a child first, using the `family_links` already on the profile, and the eligible sessions reload for that child.
- **Optimistic UI:** on submit, the entry is added to history with a temporary negative id (shown as "Saving..."), and the session is removed from the eligible list. On error, both are rolled back, the form values are restored and the server's messages are shown, e.g. the duplicate message. `errorMessages()` in `lib/api.ts` flattens DRF's `{field: [msg]}` / `{detail}` shapes.
- History is grouped by student for parents.
- `InstructorSummaryCard` (instructors and admins) shows an overall score, the response count and a bar per dimension. It is labelled as anonymized and duration-weighted. Admins get an instructor picker derived from `/classes/`, so no new endpoint was needed.

## Trade-offs / not done

- The 30-day window and "completed" status use `scheduled_date`. A real `completed_at` timestamp would be more accurate.
- Feedback can't be edited or deleted after submission. That keeps the anonymity and uniqueness story simple.
- The history and eligible lists fetch one page (`page_size=100`) instead of infinite scroll. That's plenty at this scale.
- The anonymity threshold (3 students) is a constant, not a setting. With the seed data, an instructor sees scores only after three different students have reviewed. That is intentional, but it means one test submission won't show numbers.
- I didn't add a separate sidebar route. The cards live on the dashboard as the spec asks.
