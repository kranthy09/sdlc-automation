import { useEffect, useState } from 'react'

export interface CommandItem {
  id: string
  label: string
  description?: string
  category: 'page' | 'action' | 'batch'
  shortcut?: string
  onSelect: () => void | Promise<void>
}

export function useCommandPalette() {
  const [isOpen, setIsOpen] = useState(false)
  const [search, setSearch] = useState('')

  const commands: CommandItem[] = [
    {
      id: 'goto-dashboard',
      label: 'Go to Dashboard',
      category: 'page',
      shortcut: 'g d',
      onSelect: () => (window.location.href = '/dashboard'),
    },
    {
      id: 'goto-upload',
      label: 'New Analysis',
      category: 'page',
      shortcut: 'g u',
      onSelect: () => (window.location.href = '/upload'),
    },
    {
      id: 'goto-compare',
      label: 'Compare Batches',
      category: 'page',
      shortcut: 'g c',
      onSelect: () => (window.location.href = '/compare'),
    },
    {
      id: 'goto-settings',
      label: 'Settings',
      category: 'page',
      shortcut: 'g s',
      onSelect: () => (window.location.href = '/settings'),
    },
  ]

  // Filter commands based on search
  const filtered = search
    ? commands.filter(
        (cmd) =>
          cmd.label.toLowerCase().includes(search.toLowerCase()) ||
          cmd.description?.toLowerCase().includes(search.toLowerCase()),
      )
    : commands.sort((a, b) => a.category.localeCompare(b.category))

  // Listen for Ctrl+K or Cmd+K
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
        e.preventDefault()
        setIsOpen(!isOpen)
        if (!isOpen) {
          setSearch('')
        }
      }
      // Close on Escape
      if (e.key === 'Escape' && isOpen) {
        setIsOpen(false)
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [isOpen])

  return {
    isOpen,
    setIsOpen,
    search,
    setSearch,
    filtered,
  }
}
