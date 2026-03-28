import { useEffect } from 'react'

interface KeyboardShortcuts {
  approve?: () => void
  override?: () => void
  flag?: () => void
  next?: () => void
  prev?: () => void
  submit?: () => void
  toggleHelp?: () => void
}

export function useKeyboardShortcuts(shortcuts: KeyboardShortcuts) {
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Ignore if user is typing in an input or textarea
      const target = e.target as HTMLElement
      if (target.matches('input, textarea')) return

      switch (e.key.toLowerCase()) {
        case 'a':
          if (shortcuts.approve) {
            e.preventDefault()
            shortcuts.approve()
          }
          break
        case 'o':
          if (shortcuts.override) {
            e.preventDefault()
            shortcuts.override()
          }
          break
        case 'f':
          if (shortcuts.flag) {
            e.preventDefault()
            shortcuts.flag()
          }
          break
        case 'j':
          if (shortcuts.next) {
            e.preventDefault()
            shortcuts.next()
          }
          break
        case 'k':
          if (shortcuts.prev) {
            e.preventDefault()
            shortcuts.prev()
          }
          break
        case 'enter':
          if (e.ctrlKey || e.metaKey) {
            if (shortcuts.submit) {
              e.preventDefault()
              shortcuts.submit()
            }
          }
          break
        case '?':
          if (shortcuts.toggleHelp) {
            e.preventDefault()
            shortcuts.toggleHelp()
          }
          break
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [shortcuts])
}
