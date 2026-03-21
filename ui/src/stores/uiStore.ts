import { create } from 'zustand'

// ─── Types ────────────────────────────────────────────────────────────────────

export type NotificationType = 'success' | 'error' | 'info'

export interface Notification {
  id: string
  type: NotificationType
  message: string
}

interface UIState {
  activeBatchId: string | null
  sidebarOpen: boolean
  notifications: Notification[]

  setActiveBatchId: (id: string | null) => void
  toggleSidebar: () => void
  addNotification: (n: Omit<Notification, 'id'>) => void
  dismissNotification: (id: string) => void
}

// ─── Store ────────────────────────────────────────────────────────────────────

export const useUIStore = create<UIState>((set) => ({
  activeBatchId: null,
  sidebarOpen: true,
  notifications: [],

  setActiveBatchId: (id) => set({ activeBatchId: id }),

  toggleSidebar: () => set((s) => ({ sidebarOpen: !s.sidebarOpen })),

  addNotification: (n) =>
    set((s) => ({
      notifications: [
        ...s.notifications,
        { ...n, id: crypto.randomUUID() },
      ],
    })),

  dismissNotification: (id) =>
    set((s) => ({ notifications: s.notifications.filter((n) => n.id !== id) })),
}))
