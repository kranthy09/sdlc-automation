import { Settings, Bell, Eye, RotateCw, Palette } from 'lucide-react'
import { PageHeader } from '@/components/layout/PageHeader'
import { Button } from '@/components/ui/Button'
import { useSettingsStore, type NotificationLevel, type DefaultSort } from '@/stores/settingsStore'

const NOTIFICATION_LEVELS: { label: string; value: NotificationLevel; description: string }[] = [
  {
    label: 'All',
    value: 'all',
    description: 'Receive all notifications',
  },
  {
    label: 'Important',
    value: 'important',
    description: 'Only important and critical notifications',
  },
  {
    label: 'Critical',
    value: 'critical',
    description: 'Only critical alerts',
  },
]

const ITEMS_PER_PAGE_OPTIONS = [10, 25, 50, 100]

const DEFAULT_SORT_OPTIONS: { label: string; value: DefaultSort }[] = [
  { label: 'Created date', value: 'created_at' },
  { label: 'Confidence', value: 'confidence' },
  { label: 'Status', value: 'status' },
]

export default function SettingsPage() {
  const {
    notificationLevel,
    setNotificationLevel,
    itemsPerPage,
    setItemsPerPage,
    defaultSort,
    setDefaultSort,
    darkMode,
    setDarkMode,
    autoRefresh,
    setAutoRefresh,
  } = useSettingsStore()

  return (
    <div>
      <PageHeader
        title="Settings"
        description="Customize your REQFIT experience"
      />

      <div className="space-y-6 px-6 pb-6">
        {/* Notification Settings */}
        <div className="rounded-xl border border-bg-border bg-bg-surface p-6">
          <div className="flex items-center gap-2 mb-4">
            <Bell className="h-5 w-5 text-accent" />
            <h2 className="text-lg font-semibold text-text-primary">Notifications</h2>
          </div>

          <div className="space-y-4">
            <div>
              <p className="text-sm font-medium text-text-primary mb-3">Notification level</p>
              <div className="space-y-2">
                {NOTIFICATION_LEVELS.map((level) => (
                  <label key={level.value} className="flex items-start gap-3 cursor-pointer">
                    <input
                      type="radio"
                      name="notification-level"
                      value={level.value}
                      checked={notificationLevel === level.value}
                      onChange={() => setNotificationLevel(level.value)}
                      className="mt-1"
                    />
                    <div>
                      <p className="text-sm font-medium text-text-primary">{level.label}</p>
                      <p className="text-xs text-text-muted">{level.description}</p>
                    </div>
                  </label>
                ))}
              </div>
            </div>
          </div>
        </div>

        {/* Display Settings */}
        <div className="rounded-xl border border-bg-border bg-bg-surface p-6">
          <div className="flex items-center gap-2 mb-4">
            <Eye className="h-5 w-5 text-accent" />
            <h2 className="text-lg font-semibold text-text-primary">Display</h2>
          </div>

          <div className="space-y-6">
            {/* Items per page */}
            <div>
              <label htmlFor="items-per-page" className="text-sm font-medium text-text-primary block mb-2">
                Items per page
              </label>
              <select
                id="items-per-page"
                value={itemsPerPage}
                onChange={(e) => setItemsPerPage(Number(e.target.value))}
                className="rounded-lg border border-bg-border bg-bg-raised px-3 py-2 text-sm text-text-primary focus:outline-none focus:ring-1 focus:ring-accent"
              >
                {ITEMS_PER_PAGE_OPTIONS.map((option) => (
                  <option key={option} value={option}>
                    {option} items
                  </option>
                ))}
              </select>
              <p className="text-xs text-text-muted mt-1">Controls pagination in tables and results</p>
            </div>

            {/* Default sort */}
            <div>
              <label htmlFor="default-sort" className="text-sm font-medium text-text-primary block mb-2">
                Default sort order
              </label>
              <select
                id="default-sort"
                value={defaultSort}
                onChange={(e) => setDefaultSort(e.target.value as DefaultSort)}
                className="rounded-lg border border-bg-border bg-bg-raised px-3 py-2 text-sm text-text-primary focus:outline-none focus:ring-1 focus:ring-accent"
              >
                {DEFAULT_SORT_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </div>
          </div>
        </div>

        {/* Appearance Settings */}
        <div className="rounded-xl border border-bg-border bg-bg-surface p-6">
          <div className="flex items-center gap-2 mb-4">
            <Palette className="h-5 w-5 text-accent" />
            <h2 className="text-lg font-semibold text-text-primary">Appearance</h2>
          </div>

          <div className="space-y-3">
            <label className="flex items-center gap-3 cursor-pointer">
              <input
                type="checkbox"
                checked={darkMode}
                onChange={(e) => setDarkMode(e.target.checked)}
                className="h-4 w-4 rounded border-bg-border text-accent focus:ring-accent"
              />
              <span className="text-sm font-medium text-text-primary">Dark mode</span>
            </label>
            <p className="text-xs text-text-muted ml-7">Use dark theme throughout the application</p>
          </div>
        </div>

        {/* Batch Processing Settings */}
        <div className="rounded-xl border border-bg-border bg-bg-surface p-6">
          <div className="flex items-center gap-2 mb-4">
            <RotateCw className="h-5 w-5 text-accent" />
            <h2 className="text-lg font-semibold text-text-primary">Batch Processing</h2>
          </div>

          <div className="space-y-3">
            <label className="flex items-center gap-3 cursor-pointer">
              <input
                type="checkbox"
                checked={autoRefresh}
                onChange={(e) => setAutoRefresh(e.target.checked)}
                className="h-4 w-4 rounded border-bg-border text-accent focus:ring-accent"
              />
              <span className="text-sm font-medium text-text-primary">Auto-refresh during processing</span>
            </label>
            <p className="text-xs text-text-muted ml-7">
              Automatically refresh progress while batches are running
            </p>
          </div>
        </div>

        {/* Reset to defaults */}
        <div className="rounded-xl border border-bg-border/50 bg-bg-surface/50 p-6">
          <p className="text-sm text-text-muted mb-4">
            All settings are saved automatically to your browser's local storage.
          </p>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              // Reset all settings to defaults
              localStorage.removeItem('reqfit-settings')
              window.location.reload()
            }}
            className="border border-bg-border text-gap-text hover:text-gap-text hover:bg-gap-muted/10"
          >
            Reset to defaults
          </Button>
        </div>
      </div>
    </div>
  )
}
