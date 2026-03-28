import { useLocation, useNavigate } from 'react-router-dom'
import { ChevronRight } from 'lucide-react'
import { cn } from '@/lib/utils'

const BREADCRUMB_LABELS: Record<string, string> = {
  dashboard: 'Dashboard',
  upload: 'New Analysis',
  progress: 'Progress',
  results: 'Results',
  review: 'Review',
  features: 'Feature Report',
  atom: 'Atom Details',
  settings: 'Settings',
}

export function Breadcrumbs() {
  const location = useLocation()
  const navigate = useNavigate()
  const pathname = location.pathname

  // Parse breadcrumbs from pathname
  const segments = pathname
    .split('/')
    .filter((s) => s && s !== 'dashboard') // Home redirect, so skip dashboard if it's the first

  if (segments.length === 0) return null

  const breadcrumbs = segments.map((segment, i) => {
    const path = `/${segments.slice(0, i + 1).join('/')}`
    const label = BREADCRUMB_LABELS[segment] || segment.replace(/_/g, ' ')

    return {
      label,
      path,
      isCurrent: i === segments.length - 1,
    }
  })

  return (
    <div className="flex items-center gap-1 mb-3">
      <button
        onClick={() => navigate('/dashboard')}
        className="text-xs text-text-muted hover:text-text-primary transition-colors"
      >
        Home
      </button>
      {breadcrumbs.map((crumb) => (
        <div key={crumb.path} className="flex items-center gap-1">
          <ChevronRight className="h-3.5 w-3.5 text-text-muted" />
          {crumb.isCurrent ? (
            <span className="text-xs text-text-primary font-medium">{crumb.label}</span>
          ) : (
            <button
              onClick={() => navigate(crumb.path)}
              className="text-xs text-text-muted hover:text-text-primary transition-colors"
            >
              {crumb.label}
            </button>
          )}
        </div>
      ))}
    </div>
  )
}
