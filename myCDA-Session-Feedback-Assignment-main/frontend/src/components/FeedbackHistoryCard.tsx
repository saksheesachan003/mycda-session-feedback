"use client";

import type { SessionFeedback } from "@/lib/types";
import DashboardCard from "./DashboardCard";

export type HistoryEntry = SessionFeedback & { pending?: boolean };

interface FeedbackHistoryCardProps {
  entries: HistoryEntry[];
  loading: boolean;
  error: string;
  /** Parents see entries grouped by linked student. */
  groupByStudent: boolean;
}

function Ratings({ entry }: { entry: HistoryEntry }) {
  const items = [
    ["Clarity", entry.rating_clarity],
    ["Engagement", entry.rating_engagement],
    ["Pace", entry.rating_pace],
  ] as const;
  return (
    <div className="mt-1 flex flex-wrap gap-2">
      {items.map(([label, value]) => (
        <span
          key={label}
          className="rounded-full bg-cda-mint/20 px-2 py-0.5 text-xs font-medium text-cda-navy"
        >
          {label} {value}/5
        </span>
      ))}
    </div>
  );
}

function EntryRow({ entry }: { entry: HistoryEntry }) {
  return (
    <li className={`px-5 py-3 ${entry.pending ? "opacity-60" : ""}`}>
      <div className="flex items-center justify-between">
        <p className="text-sm font-medium text-gray-900">{entry.session_display.class_name}</p>
        <p className="text-xs text-gray-500">
          {entry.pending
            ? "Saving..."
            : new Date(entry.session_display.scheduled_date).toLocaleDateString()}
        </p>
      </div>
      <Ratings entry={entry} />
      {entry.note && <p className="mt-2 text-sm text-gray-600">&ldquo;{entry.note}&rdquo;</p>}
    </li>
  );
}

export default function FeedbackHistoryCard({
  entries,
  loading,
  error,
  groupByStudent,
}: FeedbackHistoryCardProps) {
  if (loading) {
    return (
      <DashboardCard title="Feedback History">
        <p className="text-sm text-gray-400">Loading...</p>
      </DashboardCard>
    );
  }

  if (error) {
    return (
      <DashboardCard title="Feedback History">
        <p className="text-sm text-red-500">{error}</p>
      </DashboardCard>
    );
  }

  if (entries.length === 0) {
    return (
      <DashboardCard title="Feedback History">
        <p className="text-sm text-gray-500">No feedback submitted yet.</p>
      </DashboardCard>
    );
  }

  const subtitle = `${entries.length} review${entries.length !== 1 ? "s" : ""}`;

  if (!groupByStudent) {
    return (
      <DashboardCard title="Feedback History" subtitle={subtitle} flush>
        <ul className="divide-y divide-gray-100">
          {entries.map((entry) => (
            <EntryRow key={entry.id} entry={entry} />
          ))}
        </ul>
      </DashboardCard>
    );
  }

  // Entries arrive newest-first, so each group stays newest-first too.
  const groups = new Map<number, { name: string; entries: HistoryEntry[] }>();
  for (const entry of entries) {
    const group = groups.get(entry.student) ?? {
      name: entry.student_display.display_name,
      entries: [],
    };
    group.entries.push(entry);
    groups.set(entry.student, group);
  }

  return (
    <DashboardCard title="Feedback History" subtitle={subtitle} flush>
      {Array.from(groups.entries()).map(([studentId, group]) => (
        <div key={studentId}>
          <p className="border-b border-gray-100 bg-gray-50 px-5 py-2 text-xs font-semibold uppercase tracking-wide text-gray-500">
            {group.name}
          </p>
          <ul className="divide-y divide-gray-100">
            {group.entries.map((entry) => (
              <EntryRow key={entry.id} entry={entry} />
            ))}
          </ul>
        </div>
      ))}
    </DashboardCard>
  );
}
