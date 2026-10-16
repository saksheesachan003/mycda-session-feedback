"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import type { PaginatedResponse, SessionFeedback } from "@/lib/types";
import { useAuth } from "@/contexts/AuthContext";
import FeedbackFormCard from "./FeedbackFormCard";
import FeedbackHistoryCard, { type HistoryEntry } from "./FeedbackHistoryCard";

/**
 * Student/parent feedback cards. Owns the history list so the form can
 * add entries optimistically and the history card reflects them at once.
 */
export default function StudentFeedbackCards() {
  const { user } = useAuth();
  const [history, setHistory] = useState<HistoryEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  // Negative ids for optimistic entries so they never clash with real ones.
  const nextTempId = useRef(-1);

  useEffect(() => {
    api
      .get<PaginatedResponse<SessionFeedback>>("/feedback/my/?page_size=100")
      .then((res) => setHistory(res.results))
      .catch(() => setError("Could not load feedback history."))
      .finally(() => setLoading(false));
  }, []);

  const addOptimistic = useCallback((entry: SessionFeedback) => {
    const tempId = nextTempId.current--;
    setHistory((prev) => [{ ...entry, id: tempId, pending: true }, ...prev]);
    return tempId;
  }, []);

  const confirm = useCallback((tempId: number, saved: SessionFeedback) => {
    setHistory((prev) => prev.map((e) => (e.id === tempId ? saved : e)));
  }, []);

  const rollback = useCallback((tempId: number) => {
    setHistory((prev) => prev.filter((e) => e.id !== tempId));
  }, []);

  return (
    <>
      <FeedbackFormCard
        onOptimisticAdd={addOptimistic}
        onConfirm={confirm}
        onRollback={rollback}
      />
      <FeedbackHistoryCard
        entries={history}
        loading={loading}
        error={error}
        groupByStudent={user?.role === "parent"}
      />
    </>
  );
}
