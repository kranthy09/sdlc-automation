import { useState, useEffect, useRef } from 'react'
import { Search, ChevronRight } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useCommandPalette } from '@/hooks/useCommandPalette'

export function CommandPalette() {
  const { isOpen, setIsOpen, search, setSearch, filtered } = useCommandPalette()
  const [selectedIndex, setSelectedIndex] = useState(0)
  const inputRef = useRef<HTMLInputElement>(null)
  const listRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (isOpen && inputRef.current) {
      inputRef.current.focus()
      setSelectedIndex(0)
    }
  }, [isOpen])

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (!isOpen) return

      if (e.key === 'ArrowDown') {
        e.preventDefault()
        setSelectedIndex((i) => (i + 1) % filtered.length)
      } else if (e.key === 'ArrowUp') {
        e.preventDefault()
        setSelectedIndex((i) => (i - 1 + filtered.length) % filtered.length)
      } else if (e.key === 'Enter') {
        e.preventDefault()
        const cmd = filtered[selectedIndex]
        if (cmd) {
          cmd.onSelect()
          setIsOpen(false)
        }
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [isOpen, selectedIndex, filtered, setIsOpen])

  // Scroll selected item into view
  useEffect(() => {
    const items = listRef.current?.querySelectorAll('[role="option"]')
    items?.[selectedIndex]?.scrollIntoView({ block: 'nearest' })
  }, [selectedIndex])

  if (!isOpen) return null

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 z-50 bg-black/50"
        onClick={() => setIsOpen(false)}
      />

      {/* Modal */}
      <div className="fixed left-1/2 top-1/4 z-50 w-full max-w-xl -translate-x-1/2">
        <div className="rounded-lg border border-bg-border bg-bg-surface shadow-xl overflow-hidden">
          {/* Search input */}
          <div className="flex items-center gap-3 border-b border-bg-border px-4 py-3">
            <Search className="h-4 w-4 text-text-muted shrink-0" />
            <input
              ref={inputRef}
              type="text"
              placeholder="Search commands..."
              value={search}
              onChange={(e) => {
                setSearch(e.target.value)
                setSelectedIndex(0)
              }}
              className="flex-1 bg-transparent text-sm text-text-primary placeholder-text-muted focus:outline-none"
              aria-label="Search commands"
            />
            <span className="text-xs text-text-muted">Esc to close</span>
          </div>

          {/* Command list */}
          {filtered.length > 0 ? (
            <div
              ref={listRef}
              className="max-h-96 overflow-y-auto"
              role="listbox"
            >
              {filtered.map((cmd, i) => (
                <button
                  key={cmd.id}
                  role="option"
                  aria-selected={i === selectedIndex}
                  onClick={() => {
                    cmd.onSelect()
                    setIsOpen(false)
                  }}
                  onMouseEnter={() => setSelectedIndex(i)}
                  className={cn(
                    'w-full flex items-center justify-between gap-3 px-4 py-3 text-sm transition-colors',
                    i === selectedIndex
                      ? 'bg-accent/10 text-text-primary'
                      : 'text-text-secondary hover:bg-bg-raised',
                  )}
                >
                  <div className="flex items-start gap-3 flex-1 min-w-0">
                    <span className="text-xs px-1.5 py-0.5 rounded bg-bg-raised text-text-muted shrink-0 capitalize">
                      {cmd.category}
                    </span>
                    <div className="min-w-0">
                      <p className="font-medium text-text-primary">{cmd.label}</p>
                      {cmd.description && (
                        <p className="text-xs text-text-muted">{cmd.description}</p>
                      )}
                    </div>
                  </div>
                  {cmd.shortcut && (
                    <span className="text-xs text-text-muted font-mono shrink-0">
                      {cmd.shortcut}
                    </span>
                  )}
                  {i === selectedIndex && (
                    <ChevronRight className="h-4 w-4 text-accent shrink-0" />
                  )}
                </button>
              ))}
            </div>
          ) : (
            <div className="px-4 py-8 text-center">
              <p className="text-sm text-text-muted">No commands found</p>
            </div>
          )}

          {/* Footer hint */}
          <div className="border-t border-bg-border px-4 py-2 bg-bg-raised/50 text-xs text-text-muted">
            <span className="font-mono">↑↓</span> to navigate · <span className="font-mono">Enter</span> to select · <span className="font-mono">Ctrl+K</span> to toggle
          </div>
        </div>
      </div>
    </>
  )
}
