"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { ClassItem, InstructorSummary, PaginatedResponse, UserMinimal } from "@/lib/types";
import { useAuth } from "@/contexts/AuthContext";
import DashboardCard from "./DashboardCard";

const ROWS = [
  { key: "clarity", label: "Clarity" },
  { key: "engagement", label: "Engagement" },
  { key: "pace", label: "Pace" },
] as const;

function ScoreBar({ label, value }: { label: string; value: number | null }) {
  return (
    <div>
      <div className="flex items-center justify-between text-sm">
        <span className="text-gray-700">{label}</span>
        <span className="font-medium text-gray-900">
          {value === null ? "—" : value.toFixed(2)}
          <span className="text-xs text-gray-400"> / 5</span>
        </span>
      </div>
      <div className="mt-1 h-2 rounded-full bg-gray-100">
        <div
          className="h-2 rounded-full bg-cda-blue"
          style={{ width: `${value === null ? 0 : (value / 5) * 100}%` }}
        />
      </div>
    </div>
  );
}

export default function InstructorSummaryCard() {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";

  const [instructors, setInstructors] = useState<UserMinimal[]>([]);
  const [instructorId, setInstructorId] = useState<number | null>(null);
  const [summary, setSummary] = useState<InstructorSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  // Admins pick an instructor; derive the list from the classes they can see.
  useEffect(() => {
    if (!isAdmin) return;
    api
      .get<PaginatedResponse<ClassItem>>("/classes/?page_size=100")
      .then((res) => {
        const unique = new Map(res.results.map((c) => [c.instructor, c.instructor_display]));
        const list = Array.from(unique.values());
        setInstructors(list);
        setInstructorId(list[0]?.id ?? null);
        if (list.length === 0) setLoading(false);
      })
      .catch(() => {
        setError("Could not load instructors.");
        setLoading(false);
      });
  }, [isAdmin]);

  useEffect(() => {
    if (isAdmin && instructorId === null) return;
    const query = isAdmin ? `?instructor_id=${instructorId}` : "";
    setLoading(true);
    setError("");
    api
      .get<InstructorSummary>(`/feedback/instructor-summary/${query}`)
      .then(setSummary)
      .catch(() => setError("Could not load feedback summary."))
      .finally(() => setLoading(false));
  }, [isAdmin, instructorId]);

  const picker = isAdmin && instructors.length > 0 && (
    <select
      aria-label="Instructor"
      value={instructorId ?? ""}
      onChange={(e) => setInstructorId(Number(e.target.value))}
      className="rounded-md border border-gray-300 px-2 py-1 text-xs"
    >
      {instructors.map((i) => (
        <option key={i.id} value={i.id}>
          {i.display_name}
        </option>
      ))}
    </select>
  );

  const title = "Session Feedback Summary";
  const subtitle = "Anonymized · weighted by session length";

  if (loading) {
    return (
      <DashboardCard title={title} subtitle={subtitle} action={picker}>
        <p className="text-sm text-gray-400">Loading...</p>
      </DashboardCard>
    );
  }

  if (error || !summary) {
    return (
      <DashboardCard title={title} subtitle={subtitle} action={picker}>
        <p className="text-sm text-red-500">{error || "No instructors found."}</p>
      </DashboardCard>
    );
  }

  const { weighted_averages: avg } = summary;

  return (
    <DashboardCard title={title} subtitle={subtitle} action={picker}>
      <div className="space-y-4">
        <div className="flex items-end justify-between">
          <div>
            <p className="text-xs text-gray-500">Overall</p>
            <p className="text-3xl font-semibold text-cda-navy">
              {avg.overall === null ? "—" : avg.overall.toFixed(2)}
              <span className="text-base font-normal text-gray-400"> / 5</span>
            </p>
          </div>
          <div className="text-right">
            <p className="text-xs text-gray-500">Responses</p>
            <p className="text-lg font-medium text-gray-900">{summary.total_feedback}</p>
          </div>
        </div>

        {!summary.meets_anonymity_threshold && (
          <p className="rounded-md bg-cda-gold/20 px-3 py-2 text-xs text-cda-navy">
            Scores appear once at least {summary.min_students_required} different
            students have left feedback, so no individual&apos;s ratings can be identified.
          </p>
        )}

        <div className="space-y-3">
          {ROWS.map((row) => (
            <ScoreBar key={row.key} label={row.label} value={avg[row.key]} />
          ))}
        </div>

        <p className="text-xs text-gray-400">
          Aggregated across your last {summary.window_size} completed sessions (
          {summary.sessions_with_feedback} with feedback). Individual responses, names
          and notes are never shown.
        </p>
      </div>
    </DashboardCard>
  );
}
