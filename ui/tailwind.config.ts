import type { Config } from 'tailwindcss'

const config: Config = {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        // Surface hierarchy — dark enterprise theme
        bg: {
          base: '#030712',    // slate-950: page background
          surface: '#0f172a', // slate-900: card surfaces
          raised: '#1e293b',  // slate-800: elevated elements
          border: '#334155',  // slate-700: borders
        },
        // Text hierarchy
        text: {
          primary: '#f8fafc',   // slate-50
          secondary: '#94a3b8', // slate-400
          muted: '#64748b',     // slate-500
        },
        // Brand accent
        accent: {
          DEFAULT: '#3b82f6',   // blue-500
          hover: '#2563eb',     // blue-600
          muted: '#1d4ed8',     // blue-700
          glow: '#60a5fa',      // blue-400
        },
        // Classification status colors
        fit: {
          DEFAULT: '#10b981',   // emerald-500
          muted: '#065f46',     // emerald-900
          text: '#6ee7b7',      // emerald-300
        },
        partial: {
          DEFAULT: '#f59e0b',   // amber-500
          muted: '#78350f',     // amber-900
          text: '#fcd34d',      // amber-300
        },
        gap: {
          DEFAULT: '#ef4444',   // red-500
          muted: '#7f1d1d',     // red-900
          text: '#fca5a5',      // red-300
        },
        // Pipeline status
        pending: '#475569',     // slate-600
        active: '#3b82f6',      // blue-500
        complete: '#10b981',    // emerald-500
        error: '#ef4444',       // red-500
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'ui-monospace', 'monospace'],
      },
      animation: {
        'fade-in': 'fadeIn 0.2s ease-out',
        'slide-up': 'slideUp 0.25s ease-out',
        'pulse-slow': 'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'spin-slow': 'spin 3s linear infinite',
      },
      keyframes: {
        fadeIn: {
          '0%': { opacity: '0' },
          '100%': { opacity: '1' },
        },
        slideUp: {
          '0%': { opacity: '0', transform: 'translateY(8px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
      },
      boxShadow: {
        glow: '0 0 20px rgba(59, 130, 246, 0.15)',
        'glow-sm': '0 0 10px rgba(59, 130, 246, 0.1)',
      },
    },
  },
  plugins: [],
}

export default config
