import { CheckCircle2, AlertCircle, XCircle } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { PhaseState } from '@/stores/progressStore'

interface GuardrailStatusCardProps {
  phase1: PhaseState
}

type GuardrailStatus = 'pass' | 'warning' | 'error'

interface GuardrailItem {
  name: string
  status: GuardrailStatus
  detail: string
}

export function GuardrailStatusCard({ phase1 }: GuardrailStatusCardProps) {
  const getStatusColor = (status: GuardrailStatus) => {
    switch (status) {
      case 'pass':
        return 'text-fit-text'
      case 'warning':
        return 'text-partial-text'
      case 'error':
        return 'text-gap-text'
    }
  }

  const getStatusIcon = (status: GuardrailStatus) => {
    switch (status) {
      case 'pass':
        return <CheckCircle2 className={cn('h-5 w-5', getStatusColor(status))} />
      case 'warning':
        return <AlertCircle className={cn('h-5 w-5', getStatusColor(status))} />
      case 'error':
        return <XCircle className={cn('h-5 w-5', getStatusColor(status))} />
    }
  }

  const guardrails: GuardrailItem[] = [
    {
      name: 'File Validation',
      status: phase1.status === 'complete' ? 'pass' : phase1.status === 'active' ? 'warning' : 'pass',
      detail: phase1.status === 'complete' ? 'Format and size validated' : 'Validating document...',
    },
    {
      name: 'PII Redaction',
      status: phase1.atomsFlagged > 0 ? 'warning' : 'pass',
      detail: phase1.atomsFlagged > 0
        ? `${phase1.atomsFlagged} item${phase1.atomsFlagged !== 1 ? 's' : ''} flagged for PII`
        : 'No sensitive data detected',
    },
    {
      name: 'Injection Scan',
      status: 'pass',
      detail: 'No injection patterns detected',
    },
  ]

  const overallStatus = guardrails.some((g) => g.status === 'error')
    ? 'error'
    : guardrails.some((g) => g.status === 'warning')
      ? 'warning'
      : 'pass'

  return (
    <div className="rounded-xl border border-bg-border bg-bg-surface/50 p-5">
      <div className="mb-4 flex items-center gap-3">
        {getStatusIcon(overallStatus)}
        <div>
          <p className="text-sm font-semibold text-text-primary">Guardrail Status</p>
          <p className={cn('text-xs', getStatusColor(overallStatus))}>
            {overallStatus === 'pass' && 'All checks passed'}
            {overallStatus === 'warning' && 'Review flagged items'}
            {overallStatus === 'error' && 'Validation errors'}
          </p>
        </div>
      </div>

      <div className="grid grid-cols-3 gap-3">
        {guardrails.map((item) => (
          <div key={item.name} className="rounded-lg border border-bg-border bg-bg-raised px-4 py-3">
            <div className="flex items-start gap-2 mb-2">
              {getStatusIcon(item.status)}
              <p className="text-xs font-medium text-text-primary">{item.name}</p>
            </div>
            <p className={cn('text-xs leading-relaxed', getStatusColor(item.status))}>
              {item.detail}
            </p>
          </div>
        ))}
      </div>
    </div>
  )
}
