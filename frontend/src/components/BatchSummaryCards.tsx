import type { BatchSummary } from '@/types'
import StatusBadge from './ui/StatusBadge'
import ProgressBar from './ui/ProgressBar'
import { FileText, CheckCircle2, AlertTriangle, XCircle, Package, Eye, ScanLine, Users } from 'lucide-react'

interface Props { batch: BatchSummary; extraStats?: BatchExtraStats | null }

export interface BatchExtraStats {
  ocr_files: number
  matched_files: number
  unmatched_files: number
  extraction_failed: number
  non_timesheet: number
}

export default function BatchSummaryCards({ batch, extraStats }: Props) {
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

      {/* Primary cards grid */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
        <Card label="Total Files"    value={batch.total_files}          icon={<FileText    className="w-4 h-4 text-gray-500"   />} />
        <Card label="Processed"      value={batch.processed_files}       icon={<CheckCircle2 className="w-4 h-4 text-green-500" />} color="green" />
        <Card label="Needs Review"   value={batch.review_required_files} icon={<AlertTriangle className="w-4 h-4 text-yellow-500" />} color="yellow" />
        <Card label="Failed"         value={batch.failed_files}          icon={<XCircle     className="w-4 h-4 text-red-500"    />} color="red" />
        <Card label="Duplicates"     value={batch.duplicate_files}       icon={<FileText    className="w-4 h-4 text-orange-500" />} color="orange" />
        <Card label="Payroll Ready"  value={batch.payroll_ready_count}   icon={<CheckCircle2 className="w-4 h-4 text-blue-500"  />} color="blue" />
      </div>

      {/* Secondary stats row (from extra API if available) */}
      {extraStats && (
        <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
          <SmallCard label="OCR Used"          value={extraStats.ocr_files}         icon={<ScanLine  className="w-3.5 h-3.5 text-purple-500" />} />
          <SmallCard label="Matched"           value={extraStats.matched_files}      icon={<Users     className="w-3.5 h-3.5 text-green-500" />} />
          <SmallCard label="Unmatched"         value={extraStats.unmatched_files}    icon={<Users     className="w-3.5 h-3.5 text-red-500"   />} color="red" />
          <SmallCard label="Extraction Failed" value={extraStats.extraction_failed}  icon={<XCircle  className="w-3.5 h-3.5 text-red-500"   />} color="red" />
          <SmallCard label="Non-Timesheet"     value={extraStats.non_timesheet}      icon={<Eye       className="w-3.5 h-3.5 text-gray-400"  />} />
        </div>
      )}
    </div>
  )
}

function Card({
  label, value, icon, color = 'gray',
}: { label: string; value: number; icon: React.ReactNode; color?: string }) {
  const border: Record<string, string> = {
    green: 'border-l-green-400', yellow: 'border-l-yellow-400',
    red: 'border-l-red-400',     blue: 'border-l-blue-400',
    orange: 'border-l-orange-400', gray: 'border-l-gray-300',
  }
  return (
    <div className={`bg-white rounded-lg border border-gray-200 border-l-4 ${border[color] ?? border.gray} p-3`}>
      <div className="flex items-center gap-1.5 text-xs text-gray-500 mb-1">{icon} {label}</div>
      <p className="text-2xl font-bold text-gray-800">{value.toLocaleString()}</p>
    </div>
  )
}

function SmallCard({
  label, value, icon, color = 'gray',
}: { label: string; value: number; icon: React.ReactNode; color?: string }) {
  const bg: Record<string, string> = { red: 'bg-red-50 border-red-200', gray: 'bg-gray-50 border-gray-200' }
  return (
    <div className={`rounded-lg border ${bg[color] ?? bg.gray} px-3 py-2 flex items-center justify-between`}>
      <div className="flex items-center gap-1.5 text-xs text-gray-600">{icon} {label}</div>
      <span className="text-sm font-semibold text-gray-800">{value.toLocaleString()}</span>
    </div>
  )
}
