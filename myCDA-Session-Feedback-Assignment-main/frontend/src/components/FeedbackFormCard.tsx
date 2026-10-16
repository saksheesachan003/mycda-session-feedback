"use client";

import { useEffect, useRef, useState } from "react";
import { api, errorMessages } from "@/lib/api";
import type {
  PaginatedResponse,
  RatingDimension,
  Session,
  SessionFeedback,
  SessionFeedbackPayload,
  UserMinimal,
} from "@/lib/types";
import { useAuth } from "@/contexts/AuthContext";
import DashboardCard from "./DashboardCard";
import StarRating from "./StarRating";

const NOTE_LIMIT = 500;

const DIMENSIONS: { key: RatingDimension; label: string; description: string }[] = [
  { key: "clarity", label: "Clarity", description: "How clearly were concepts explained?" },
  { key: "engagement", label: "Engagement", description: "How engaging was the session?" },
  { key: "pace", label: "Pace", description: "Did the pacing feel right?" },
];

const EMPTY_RATINGS: Record<RatingDimension, number> = { clarity: 0, engagement: 0, pace: 0 };

interface FeedbackFormCardProps {
  /** Add a provisional entry to the history; returns its temporary id. */
  onOptimisticAdd: (entry: SessionFeedback) => number;
  onConfirm: (tempId: number, saved: SessionFeedback) => void;
  onRollback: (tempId: number) => void;
}

export default function FeedbackFormCard({
  onOptimisticAdd,
  onConfirm,
  onRollback,
}: FeedbackFormCardProps) {
  const { user } = useAuth();
  const isParent = user?.role === "parent";
  const children: UserMinimal[] = (user?.family_links ?? []).map((l) => l.student_display);

  // Students always submit for themselves; parents must pick a child.
  const [studentId, setStudentId] = useState<number | null>(
    isParent ? null : user?.id ?? null
  );
  const studentIdRef = useRef(studentId);
  studentIdRef.current = studentId;

  const [sessions, setSessions] = useState<Session[]>([]);
  const [loadingSessions, setLoadingSessions] = useState(false);
  const [loadError, setLoadError] = useState("");

  const [sessionId, setSessionId] = useState<number | "">("");
  const [ratings, setRatings] = useState(EMPTY_RATINGS);
  const [note, setNote] = useState("");
  const [errors, setErrors] = useState<string[]>([]);
  const [success, setSuccess] = useState("");

  useEffect(() => {
    if (studentId === null) {
      setSessions([]);
      return;
    }
    const query = isParent ? `?student=${studentId}&page_size=100` : "?page_size=100";
    setLoadingSessions(true);
    setLoadError("");
    api
      .get<PaginatedResponse<Session>>(`/feedback/eligible-sessions/${query}`)
      .then((res) => setSessions(res.results))
      .catch(() => setLoadError("Could not load sessions."))
      .finally(() => setLoadingSessions(false));
  }, [studentId, isParent]);

  if (!user) return null;

  const resetForm = () => {
    setSessionId("");
    setRatings(EMPTY_RATINGS);
    setNote("");
  };

  const handleStudentChange = (value: string) => {
    setStudentId(value ? Number(value) : null);
    resetForm();
    setErrors([]);
    setSuccess("");
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErrors([]);
    setSuccess("");

    const session = sessions.find((s) => s.id === sessionId);
    const student = isParent ? children.find((c) => c.id === studentId) : user;
    if (!session || !student) {
      setErrors(["Choose a session to review."]);
      return;
    }
    if (DIMENSIONS.some((d) => ratings[d.key] === 0)) {
      setErrors(["Please rate all three dimensions."]);
      return;
    }

    const payload: SessionFeedbackPayload = {
      session: session.id,
      rating_clarity: ratings.clarity,
      rating_engagement: ratings.engagement,
      rating_pace: ratings.pace,
      note: note.trim(),
    };
    if (isParent) payload.student = student.id;

    // Optimistic update: show it in history and drop it from the
    // eligible list straight away; undo both if the server rejects it.
    const snapshot = { sessionId, ratings, note };
    const submittedFor = studentId;
    const now = new Date().toISOString();
    const tempId = onOptimisticAdd({
      id: 0,
      session: session.id,
      session_display: session,
      student: student.id,
      student_display: { id: student.id, display_name: student.display_name, role: "student" },
      rating_clarity: ratings.clarity,
      rating_engagement: ratings.engagement,
      rating_pace: ratings.pace,
      note: payload.note,
      created_by_display: user.display_name,
      created_at: now,
      updated_at: now,
    });
    setSessions((prev) => prev.filter((s) => s.id !== session.id));
    resetForm();
    setSuccess("Thanks! Your feedback was submitted.");

    try {
      const saved = await api.post<SessionFeedback>("/feedback/", payload);
      onConfirm(tempId, saved);
    } catch (err) {
      onRollback(tempId);
      setSuccess("");
      setErrors(errorMessages(err, "Could not submit feedback. Please try again."));
      // Only restore the form if the user hasn't switched student meanwhile.
      if (studentIdRef.current === submittedFor) {
        setSessions((prev) =>
          [...prev, session].sort((a, b) => b.scheduled_date.localeCompare(a.scheduled_date))
        );
        setSessionId(snapshot.sessionId);
        setRatings(snapshot.ratings);
        setNote(snapshot.note);
      }
    }
  };

  return (
    <DashboardCard title="Leave Session Feedback" subtitle="Completed sessions from the last 30 days">
      <form onSubmit={handleSubmit} className="space-y-4">
        {isParent && (
          <div>
            <label htmlFor="feedback-student" className="text-xs text-gray-500">
              Submitting for
            </label>
            <select
              id="feedback-student"
              value={studentId ?? ""}
              onChange={(e) => handleStudentChange(e.target.value)}
              className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
            >
              <option value="">Select a student...</option>
              {children.map((child) => (
                <option key={child.id} value={child.id}>
                  {child.display_name}
                </option>
              ))}
            </select>
          </div>
        )}

        {studentId !== null && (
          <div>
            <label htmlFor="feedback-session" className="text-xs text-gray-500">
              Session
            </label>
            {loadingSessions ? (
              <p className="mt-1 text-sm text-gray-400">Loading...</p>
            ) : loadError ? (
              <p className="mt-1 text-sm text-red-500">{loadError}</p>
            ) : sessions.length === 0 ? (
              <p className="mt-1 text-sm text-gray-500">
                No sessions waiting for feedback right now.
              </p>
            ) : (
              <select
                id="feedback-session"
                value={sessionId}
                onChange={(e) => setSessionId(e.target.value ? Number(e.target.value) : "")}
                className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
              >
                <option value="">Select a session...</option>
                {sessions.map((s) => (
                  <option key={s.id} value={s.id}>
                    {new Date(s.scheduled_date).toLocaleDateString()} · {s.class_name}
                    {s.topic ? ` · ${s.topic}` : ""}
                  </option>
                ))}
              </select>
            )}
          </div>
        )}

        {sessionId !== "" && (
          <>
            {DIMENSIONS.map((d) => (
              <StarRating
                key={d.key}
                label={d.label}
                description={d.description}
                value={ratings[d.key]}
                onChange={(value) => setRatings((prev) => ({ ...prev, [d.key]: value }))}
              />
            ))}

            <div>
              <label htmlFor="feedback-note" className="text-xs text-gray-500">
                Note (optional)
              </label>
              <textarea
                id="feedback-note"
                rows={3}
                maxLength={NOTE_LIMIT}
                value={note}
                onChange={(e) => setNote(e.target.value)}
                className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
              />
              <p className="mt-1 text-right text-xs text-gray-400">
                {note.length}/{NOTE_LIMIT}
              </p>
            </div>

            <button
              type="submit"
              className="rounded-md bg-cda-navy px-4 py-2 text-sm font-medium text-white hover:bg-cda-navy/90"
            >
              Submit feedback
            </button>
          </>
        )}

        {errors.length > 0 && (
          <ul className="space-y-1 rounded-md bg-red-50 px-3 py-2 text-sm text-red-600">
            {errors.map((msg) => (
              <li key={msg}>{msg}</li>
            ))}
          </ul>
        )}
        {success && <p className="text-sm text-green-600">{success}</p>}
      </form>
    </DashboardCard>
  );
}
