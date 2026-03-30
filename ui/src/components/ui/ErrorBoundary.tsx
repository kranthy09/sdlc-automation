import React, { ReactNode } from 'react'
import { AlertCircle } from 'lucide-react'
import { Button } from './Button'

interface ErrorBoundaryProps {
  children: ReactNode
  fallback?: (error: Error, reset: () => void) => ReactNode
}

interface ErrorBoundaryState {
  hasError: boolean
  error: Error | null
}

export class ErrorBoundary extends React.Component<ErrorBoundaryProps, ErrorBoundaryState> {
  constructor(props: ErrorBoundaryProps) {
    super(props)
    this.state = { hasError: false, error: null }
  }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { hasError: true, error }
  }

  componentDidCatch(error: Error) {
    console.error('ErrorBoundary caught:', error)
  }

  resetError = () => {
    this.setState({ hasError: false, error: null })
  }

  render() {
    if (this.state.hasError && this.state.error) {
      if (this.props.fallback) {
        return this.props.fallback(this.state.error, this.resetError)
      }

      return (
        <div className="flex items-center justify-center min-h-96 p-6">
          <div className="max-w-md">
            <div className="flex justify-center mb-4">
              <AlertCircle className="h-12 w-12 text-partial-text" />
            </div>
            <h2 className="text-lg font-semibold text-text-primary text-center mb-2">
              Something went wrong
            </h2>
            <p className="text-sm text-text-secondary text-center mb-4">
              {this.state.error.message || 'An unexpected error occurred'}
            </p>
            <div className="flex justify-center gap-2">
              <Button onClick={this.resetError}>Try again</Button>
            </div>
          </div>
        </div>
      )
    }

    return this.props.children
  }
}
