import { Outlet, NavLink } from 'react-router-dom'
import {
  LayoutDashboard,
  Upload,
  Activity,
  Table2,
  ClipboardCheck,
  ChevronLeft,
  ChevronRight,
  Cpu,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { useUIStore } from '@/stores/uiStore'
import { ToastRegion } from '@/components/ui/Toast'

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
  const { sidebarOpen, toggleSidebar } = useUIStore()

  return (
    <div className="flex h-screen overflow-hidden bg-bg-base">
      {/* ── Sidebar ── */}
      <aside
        className={cn(
          'flex flex-col border-r border-bg-border bg-bg-surface transition-all duration-200',
          sidebarOpen ? 'w-56' : 'w-14',
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
              <p className="truncate text-[10px] text-text-muted">DYNAFIT Platform</p>
            </div>
          )}
        </div>

        {/* Nav */}
        <nav className="flex-1 space-y-1 p-2">
          {NAV.map((item) => (
            <NavItem key={item.to} {...item} collapsed={!sidebarOpen} />
          ))}
        </nav>

        {/* Collapse toggle */}
        <button
          onClick={toggleSidebar}
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
          <div className="flex items-center gap-2">
            <Activity className="h-4 w-4 text-accent" />
            <span className="text-sm font-medium text-text-secondary">
              D365 F&amp;O Requirement Fitment Engine
            </span>
          </div>
          <div className="ml-auto flex items-center gap-3">
            <span className="h-2 w-2 rounded-full bg-complete animate-pulse-slow" />
            <span className="text-xs text-text-muted">System online</span>
          </div>
        </header>

        {/* Page content */}
        <main className="flex-1 overflow-y-auto">
          <Outlet />
        </main>
      </div>

      <ToastRegion />
    </div>
  )
}
