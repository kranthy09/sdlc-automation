import { useState } from 'react'
import { Outlet, NavLink, useNavigate } from 'react-router-dom'
import {
  LayoutDashboard,
  Upload,
  Activity,
  ChevronLeft,
  ChevronRight,
  Cpu,
  Bell,
  Menu,
  Settings,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { useUIStore } from '@/stores/uiStore'
import { ToastRegion } from '@/components/ui/Toast'
import { ConnectionIndicator } from '@/components/ui/ConnectionIndicator'
import { NotificationHistory } from '@/components/layout/NotificationHistory'
import { CommandPalette } from '@/components/layout/CommandPalette'

const NAV = [
  { to: '/dashboard', icon: LayoutDashboard, label: 'Dashboard' },
  { to: '/upload', icon: Upload, label: 'Upload' },
] as const

function NavItem({
  to,
  icon: Icon,
  label,
  collapsed,
}: {
  to: string
  icon: React.ComponentType<{ className?: string }>
  label: string
  collapsed: boolean
}) {
  return (
    <NavLink
      to={to}
      className={({ isActive }) =>
        cn(
          'flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors',
          'hover:bg-bg-raised hover:text-text-primary',
          isActive
            ? 'bg-accent/10 text-accent border border-accent/20'
            : 'text-text-secondary border border-transparent',
          collapsed && 'justify-center px-2',
        )
      }
    >
      <Icon className="h-4 w-4 shrink-0" />
      {!collapsed && <span>{label}</span>}
    </NavLink>
  )
}

export function AppShell() {
  const navigate = useNavigate()
  const { sidebarOpen, toggleSidebar, notificationHistory } = useUIStore()
  const [historyOpen, setHistoryOpen] = useState(false)
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false)

  return (
    <div className="flex h-screen overflow-hidden bg-bg-base">
      {/* Skip-to-content link */}
      <a
        href="#main-content"
        className="absolute left-0 top-0 z-50 -translate-y-12 rounded bg-accent px-4 py-2 text-sm font-medium text-white focus:translate-y-0"
      >
        Skip to main content
      </a>

      {/* ── Sidebar ── */}
      <aside
        aria-label="Navigation sidebar"
        className={cn(
          'flex flex-col border-r border-bg-border bg-bg-surface transition-all duration-200',
          'fixed inset-y-0 left-0 z-40 lg:relative lg:z-0',
          sidebarOpen ? 'w-56' : 'w-14',
          !mobileMenuOpen && 'hidden lg:flex',
          mobileMenuOpen && 'flex',
        )}
      >
        {/* Logo */}
        <div
          className={cn(
            'flex h-14 items-center border-b border-bg-border px-3 gap-2',
            !sidebarOpen && 'justify-center',
          )}
        >
          <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-accent">
            <Cpu className="h-4 w-4 text-white" />
          </div>
          {sidebarOpen && (
            <div className="overflow-hidden">
              <p className="truncate text-xs font-semibold text-text-primary leading-tight">
                Enterprise AI
              </p>
              <p className="truncate text-[10px] text-text-muted">REQFIT Platform</p>
            </div>
          )}
        </div>

        {/* Nav */}
        <nav className="flex-1 space-y-1 p-2" aria-label="Main navigation">
          {NAV.map((item) => (
            <NavItem key={item.to} {...item} collapsed={!sidebarOpen} />
          ))}
        </nav>

        {/* Collapse toggle */}
        <button
          onClick={toggleSidebar}
          aria-label={sidebarOpen ? 'Collapse sidebar' : 'Expand sidebar'}
          className={cn(
            'flex items-center gap-2 border-t border-bg-border p-3 text-xs text-text-muted',
            'hover:text-text-primary transition-colors',
            !sidebarOpen && 'justify-center',
          )}
        >
          {sidebarOpen ? (
            <>
              <ChevronLeft className="h-4 w-4 shrink-0" />
              <span>Collapse</span>
            </>
          ) : (
            <ChevronRight className="h-4 w-4 shrink-0" />
          )}
        </button>
      </aside>

      {/* ── Main content ── */}
      <div className="flex flex-1 flex-col overflow-hidden">
        {/* Topbar */}
        <header className="flex h-14 items-center border-b border-bg-border bg-bg-surface px-6">
          <button
            onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
            aria-label="Toggle navigation menu"
            className="lg:hidden mr-3 p-2 rounded-lg hover:bg-bg-raised transition-colors"
            title="Toggle menu"
          >
            <Menu className="h-5 w-5 text-text-muted" />
          </button>
          <div className="flex items-center gap-2">
            <Activity className="h-4 w-4 text-accent" />
            <span className="text-sm font-medium text-text-secondary">
              D365 F&amp;O Requirement Fitment Engine
            </span>
          </div>
          <div className="ml-auto flex items-center gap-2">
            <ConnectionIndicator status="connected" />
            <button
              onClick={() => navigate('/settings')}
              aria-label="Settings"
              className="p-2 rounded-lg hover:bg-bg-raised transition-colors"
              title="Settings"
            >
              <Settings className="h-4 w-4 text-text-muted" />
            </button>
            <button
              onClick={() => setHistoryOpen(!historyOpen)}
              aria-label={`Notification history${notificationHistory.length > 0 ? `, ${notificationHistory.length} items` : ''}`}
              className="relative p-2 rounded-lg hover:bg-bg-raised transition-colors"
              title="Notification history"
            >
              <Bell className="h-4 w-4 text-text-muted" />
              {notificationHistory.length > 0 && (
                <span className="absolute top-1 right-1 h-2 w-2 rounded-full bg-partial-text" aria-hidden="true" />
              )}
            </button>
          </div>
        </header>

        {/* Page content */}
        <main id="main-content" className="flex-1 overflow-y-auto" role="main">
          <Outlet />
        </main>
      </div>

      {/* Mobile menu backdrop */}
      {mobileMenuOpen && (
        <div
          className="fixed inset-0 z-30 bg-black/50 lg:hidden"
          onClick={() => setMobileMenuOpen(false)}
        />
      )}

      <CommandPalette />
      <ToastRegion />
      <NotificationHistory open={historyOpen} onClose={() => setHistoryOpen(false)} />
    </div>
  )
}
