import { create } from 'zustand'

// ─── Types ────────────────────────────────────────────────────────────────────

export type NotificationType = 'success' | 'error' | 'info'

export interface Notification {
  id: string
  type: NotificationType
  message: string
  timestamp?: number
}

interface UIState {
  activeBatchId: string | null
  sidebarOpen: boolean
  notifications: Notification[]
  notificationHistory: Notification[]

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
  notificationHistory: [],

  setActiveBatchId: (id) => set({ activeBatchId: id }),

  toggleSidebar: () => set((s) => ({ sidebarOpen: !s.sidebarOpen })),

  addNotification: (n) =>
    set((s) => {
      const notification = { ...n, id: crypto.randomUUID(), timestamp: Date.now() }
      return {
        notifications: [...s.notifications, notification],
        notificationHistory: [notification, ...s.notificationHistory].slice(0, 50),
      }
    }),

  dismissNotification: (id) =>
    set((s) => {
      const notification = s.notifications.find((n) => n.id === id)
      return {
        notifications: s.notifications.filter((n) => n.id !== id),
        notificationHistory: notification
          ? [notification, ...s.notificationHistory].slice(0, 50)
          : s.notificationHistory,
      }
    }),
}))
