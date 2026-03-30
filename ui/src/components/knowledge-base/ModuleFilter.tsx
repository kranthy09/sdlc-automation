import { cn } from '@/lib/utils'

interface ModuleFilterProps {
  modules: string[]
  moduleCounts: Record<string, number>
  selectedModule: string | null
  onModuleSelect: (module: string | null) => void
}

export function ModuleFilter({
  modules,
  moduleCounts,
  selectedModule,
  onModuleSelect,
}: ModuleFilterProps) {
  if (modules.length === 0) {
    return null
  }

  return (
    <div className="flex flex-wrap gap-2">
      {/* All button */}
      <button
        onClick={() => onModuleSelect(null)}
        aria-pressed={selectedModule === null}
        aria-label="Show all modules"
        className={cn(
          'inline-flex items-center gap-2 rounded-lg px-3 py-2 text-xs font-medium transition-colors',
          'focus:outline-none focus:ring-2 focus:ring-accent focus:ring-offset-2 focus:ring-offset-bg-base',
          selectedModule === null
            ? 'bg-accent text-white'
            : 'bg-bg-raised text-text-secondary hover:text-text-primary border border-bg-border hover:border-accent/50',
        )}
      >
        All
      </button>

      {/* Module buttons */}
      {modules.map((module) => (
        <button
          key={module}
          onClick={() => onModuleSelect(selectedModule === module ? null : module)}
          aria-pressed={selectedModule === module}
          aria-label={`Filter by ${module} module (${moduleCounts[module] ?? 0} documents)`}
          className={cn(
            'inline-flex items-center gap-2 rounded-lg px-3 py-2 text-xs font-medium transition-colors',
            'focus:outline-none focus:ring-2 focus:ring-accent focus:ring-offset-2 focus:ring-offset-bg-base',
            selectedModule === module
              ? 'bg-accent text-white'
              : 'bg-bg-raised text-text-secondary hover:text-text-primary border border-bg-border hover:border-accent/50',
          )}
        >
          {module}
          <span className={cn(
            'rounded-full text-[10px] font-semibold px-1.5 py-0.5',
            selectedModule === module
              ? 'bg-white/20 text-white'
              : 'bg-bg-border text-text-muted',
          )}>
            {moduleCounts[module] ?? 0}
          </span>
        </button>
      ))}
    </div>
  )
}
