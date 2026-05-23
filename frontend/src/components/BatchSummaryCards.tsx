import type { BatchSummary } from '@/types'
import StatusBadge from './ui/StatusBadge'
import ProgressBar from './ui/ProgressBar'
import { FileText, CheckCircle2, AlertTriangle, XCircle, Package } from 'lucide-react'

interface Props { batch: BatchSummary }

export default function BatchSummaryCards({ batch }: Props) {
  const processed = batch.total_files > 0
    ? Math.round((batch.processed_files / batch.total_files) * 100)
    : 0

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold text-gray-900 flex items-center gap-2">
            <Package className="w-5 h-5 text-blue-600" />
            {batch.source_name}
          </h2>
          <p className="text-sm text-gray-500 mt-0.5">Batch ID: {batch.id}</p>
        </div>
        <StatusBadge status={batch.status} />
      </div>

      {/* Progress */}
      <ProgressBar
        value={processed}
        label={`Processing progress (${batch.processed_files} / ${batch.total_files} files)`}
        color={batch.failed_files > 0 ? 'red' : 'blue'}
      />

      {/* Cards grid */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
        <Card label="Total Files" value={batch.total_files} icon={<FileText className="w-4 h-4 text-gray-500" />} />
        <Card label="Processed" value={batch.processed_files} icon={<CheckCircle2 className="w-4 h-4 text-green-500" />} color="green" />
        <Card label="Needs Review" value={batch.review_required_files} icon={<AlertTriangle className="w-4 h-4 text-yellow-500" />} color="yellow" />
        <Card label="Failed" value={batch.failed_files} icon={<XCircle className="w-4 h-4 text-red-500" />} color="red" />
        <Card label="Duplicates" value={batch.duplicate_files} icon={<FileText className="w-4 h-4 text-orange-500" />} color="orange" />
        <Card label="Payroll Ready" value={batch.payroll_ready_count} icon={<CheckCircle2 className="w-4 h-4 text-blue-500" />} color="blue" />
      </div>
    </div>
  )
}

function Card({ label, value, icon, color = 'gray' }: { label: string; value: number; icon: React.ReactNode; color?: string }) {
  const border = { green: 'border-l-green-400', yellow: 'border-l-yellow-400', red: 'border-l-red-400', blue: 'border-l-blue-400', orange: 'border-l-orange-400', gray: 'border-l-gray-300' }
  return (
    <div className={`bg-white rounded-lg border border-gray-200 border-l-4 ${border[color as keyof typeof border] ?? border.gray} p-3`}>
      <div className="flex items-center gap-1.5 text-xs text-gray-500 mb-1">
        {icon} {label}
      </div>
      <p className="text-2xl font-bold text-gray-800">{value.toLocaleString()}</p>
    </div>
  )
}
