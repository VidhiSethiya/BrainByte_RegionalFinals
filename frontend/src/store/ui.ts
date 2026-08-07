/**
 * UI state only.
 *
 * Filters, drawer open/closed, the selected row id. Never a ticket, never a decision,
 * never anything TanStack Query owns — two copies of server data is how a UI starts
 * showing two different answers to the same question.
 */

import { create } from "zustand";

export interface QueueFilters {
  q?: string;
  severity?: string;
  status?: string;
  assigned_team?: string;
  category?: string;
  environment?: string;
  needs_human?: string;
  page: number;
  page_size: number;
  sort: string;
  order: "asc" | "desc";
}

export interface HistoryFilters extends QueueFilters {
  /** Derived server-side filter: closed = resolved or synced. */
  state?: "open" | "closed" | "all";
  from?: string;
  to?: string;
}

const DAY_MS = 24 * 60 * 60 * 1000;

const QUEUE_DEFAULTS: QueueFilters = {
  page: 1,
  page_size: 10,
  sort: "priority_score",
  order: "desc",
};

/**
 * History opens on what it is for: the last thirty days of closed work. Anything
 * wider is a deliberate act, not the state you land in.
 */
const HISTORY_DEFAULTS: HistoryFilters = {
  page: 1,
  page_size: 10,
  sort: "created_at",
  order: "desc",
  state: "closed",
  from: new Date(Date.now() - 30 * DAY_MS).toISOString(),
  to: new Date().toISOString(),
};

interface UiState {
  queueFilters: QueueFilters;
  historyFilters: HistoryFilters;
  selectedTicketId: string | null;
  drawerOpen: boolean;
  voiceEnabled: boolean;

  setQueueFilters: (patch: Partial<QueueFilters>) => void;
  resetQueueFilters: () => void;
  setHistoryFilters: (patch: Partial<HistoryFilters>) => void;
  resetHistoryFilters: () => void;

  openTicket: (id: string) => void;
  closeDrawer: () => void;
  selectTicket: (id: string | null) => void;
  setVoiceEnabled: (enabled: boolean) => void;
}

/** Any filter change resets paging — page 3 of a different result set is a bug. */
const withPageReset = <T extends { page: number }>(current: T, patch: Partial<T>): T => {
  const changesFilter = Object.keys(patch).some((key) => key !== "page");
  return { ...current, ...patch, page: changesFilter && patch.page === undefined ? 1 : patch.page ?? current.page };
};

export const useUiStore = create<UiState>((set) => ({
  queueFilters: QUEUE_DEFAULTS,
  historyFilters: HISTORY_DEFAULTS,
  selectedTicketId: null,
  drawerOpen: false,
  voiceEnabled: true,

  setQueueFilters: (patch) => set((state) => ({ queueFilters: withPageReset(state.queueFilters, patch) })),
  resetQueueFilters: () => set({ queueFilters: QUEUE_DEFAULTS }),
  setHistoryFilters: (patch) => set((state) => ({ historyFilters: withPageReset(state.historyFilters, patch) })),
  resetHistoryFilters: () => set({ historyFilters: HISTORY_DEFAULTS }),

  openTicket: (id) => set({ selectedTicketId: id, drawerOpen: true }),
  closeDrawer: () => set({ drawerOpen: false }),
  selectTicket: (id) => set({ selectedTicketId: id }),
  setVoiceEnabled: (voiceEnabled) => set({ voiceEnabled }),
}));
