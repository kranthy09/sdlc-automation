import { create } from 'zustand'
import { persist } from 'zustand/middleware'

// ─── Types ────────────────────────────────────────────────────────────────────

export type NotificationLevel = 'all' | 'important' | 'critical'
export type DefaultSort = 'created_at' | 'confidence' | 'status'

interface SettingsState {
  // Notification preferences
  notificationLevel: NotificationLevel
  setNotificationLevel: (level: NotificationLevel) => void

  // Display preferences
  itemsPerPage: number
  setItemsPerPage: (count: number) => void

  defaultSort: DefaultSort
  setDefaultSort: (sort: DefaultSort) => void

  // Theme
  darkMode: boolean
  setDarkMode: (enabled: boolean) => void

  // Batch processing
  autoRefresh: boolean
  setAutoRefresh: (enabled: boolean) => void
}

// ─── Store ────────────────────────────────────────────────────────────────────

export const useSettingsStore = create<SettingsState>()(
  persist(
    (set) => ({
      // Notification preferences
      notificationLevel: 'important',
      setNotificationLevel: (level) => set({ notificationLevel: level }),

      // Display preferences
      itemsPerPage: 25,
      setItemsPerPage: (count) => set({ itemsPerPage: count }),

      defaultSort: 'created_at',
      setDefaultSort: (sort) => set({ defaultSort: sort }),

      // Theme
      darkMode: true,
      setDarkMode: (enabled) => set({ darkMode: enabled }),

      // Batch processing
      autoRefresh: true,
      setAutoRefresh: (enabled) => set({ autoRefresh: enabled }),
    }),
    {
      name: 'reqfit-settings',
      version: 1,
    },
  ),
)
