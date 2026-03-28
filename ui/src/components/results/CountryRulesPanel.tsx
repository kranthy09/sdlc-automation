import { Globe, AlertCircle, CheckCircle2 } from 'lucide-react'
import { cn } from '@/lib/utils'

interface CountryRule {
  country: string
  rule: string
  appliedCount: number
  status: 'active' | 'warning' | 'pending'
}

interface CountryRulesPanelProps {
  country: string
  rules?: string[]
}

const COUNTRY_RULE_EXAMPLES: Record<string, CountryRule[]> = {
  US: [
    {
      country: 'US',
      rule: 'SEC compliance — Financial reporting modules require audit trail',
      appliedCount: 42,
      status: 'active',
    },
    {
      country: 'US',
      rule: 'HIPAA certified modules only for health data processing',
      appliedCount: 15,
      status: 'active',
    },
  ],
  EU: [
    {
      country: 'EU',
      rule: 'GDPR data residency — All personal data processed in EU data centers',
      appliedCount: 78,
      status: 'active',
    },
    {
      country: 'EU',
      rule: 'VAT compliance — Tax calculation aligned with member state rules',
      appliedCount: 29,
      status: 'active',
    },
  ],
  JP: [
    {
      country: 'JP',
      rule: 'Act on Protection of Personal Information (APPI) compliance',
      appliedCount: 12,
      status: 'active',
    },
    {
      country: 'JP',
      rule: 'Yen currency and locale-specific date/number formatting',
      appliedCount: 45,
      status: 'active',
    },
  ],
  IN: [
    {
      country: 'IN',
      rule: 'GST compliance — Tax category mapping for Indian market',
      appliedCount: 67,
      status: 'active',
    },
  ],
}

const STATUS_CONFIG = {
  active: { icon: CheckCircle2, color: 'text-fit-text', bg: 'bg-fit-muted/10' },
  warning: { icon: AlertCircle, color: 'text-partial-text', bg: 'bg-partial-muted/10' },
  pending: { icon: AlertCircle, color: 'text-text-muted', bg: 'bg-bg-raised' },
}

export function CountryRulesPanel({ country, rules }: CountryRulesPanelProps) {
  const applicableRules = COUNTRY_RULE_EXAMPLES[country] || []

  if (applicableRules.length === 0) {
    return (
      <div className="rounded-xl border border-bg-border bg-bg-surface/50 p-5">
        <div className="flex items-center gap-2 mb-3">
          <Globe className="h-4 w-4 text-text-muted" />
          <p className="text-sm font-medium text-text-primary">Country-Specific Rules</p>
        </div>
        <p className="text-xs text-text-muted">No country-specific rules configured for {country}.</p>
      </div>
    )
  }

  return (
    <div className="rounded-xl border border-bg-border bg-bg-surface/50 p-5">
      <div className="flex items-center gap-2 mb-4">
        <Globe className="h-4 w-4 text-text-muted" />
        <p className="text-sm font-medium text-text-primary">Country-Specific Rules</p>
        <span className="ml-auto inline-flex items-center rounded-full bg-bg-raised px-2.5 py-0.5 text-xs font-medium text-text-muted">
          {country}
        </span>
      </div>

      <div className="space-y-3">
        {applicableRules.map((rule, i) => {
          const StatusIcon = STATUS_CONFIG[rule.status].icon
          const config = STATUS_CONFIG[rule.status]

          return (
            <div key={i} className={cn('rounded-lg border border-bg-border px-4 py-3', config.bg)}>
              <div className="flex items-start gap-3">
                <StatusIcon className={cn('h-5 w-5 mt-0.5 shrink-0', config.color)} />
                <div className="flex-1">
                  <p className="text-sm text-text-primary font-medium">{rule.rule}</p>
                  <p className={cn('text-xs mt-1', config.color)}>
                    Applied to {rule.appliedCount} requirement{rule.appliedCount !== 1 ? 's' : ''}
                  </p>
                </div>
              </div>
            </div>
          )
        })}
      </div>

      {rules && rules.length > 0 && (
        <div className="mt-4 rounded-lg border border-bg-border/50 bg-bg-raised/50 p-3">
          <p className="text-xs font-medium text-text-muted mb-2">Custom Rules</p>
          <ul className="space-y-1">
            {rules.map((rule, i) => (
              <li key={i} className="text-xs text-text-secondary flex items-start gap-2">
                <span className="mt-1">•</span>
                <span>{rule}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
