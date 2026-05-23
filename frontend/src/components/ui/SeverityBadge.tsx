import clsx from 'clsx'
import { AlertOctagon, AlertTriangle, Info, CheckCircle } from 'lucide-react'

const SEV = {
  BLOCKER: { cls: 'bg-red-100 text-red-800 border border-red-200', icon: AlertOctagon },
  ERROR: { cls: 'bg-red-50 text-red-700 border border-red-100', icon: AlertOctagon },
  WARNING: { cls: 'bg-yellow-50 text-yellow-800 border border-yellow-200', icon: AlertTriangle },
  INFO: { cls: 'bg-blue-50 text-blue-700 border border-blue-100', icon: Info },
}

export default function SeverityBadge({ severity }: { severity: string }) {
  const cfg = SEV[severity as keyof typeof SEV] ?? { cls: 'bg-gray-100 text-gray-600', icon: Info }
  const Icon = cfg.icon
  return (
    <span className={clsx('inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium', cfg.cls)}>
      <Icon className="w-3 h-3" />
      {severity}
    </span>
  )
}
