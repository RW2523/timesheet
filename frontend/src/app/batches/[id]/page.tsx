'use client'
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import Link from 'next/link'
import { getBatch, getBatchStatus, cancelBatch, listValidation } from '@/lib/api'
import BatchSummaryCards from '@/components/BatchSummaryCards'
import { FileText, AlertTriangle, CheckCircle2, Download, StopCircle, Loader2 } from 'lucide-react'
import ProgressBar from '@/components/ui/ProgressBar'

interface Props { params: { id: string } }

const TABS = [
  { key: 'files', label: 'Files', icon: FileText, href: (id: string) => `/batches/${id}/files` },
  { key: 'validation', label: 'Validation Issues', icon: AlertTriangle, href: (id: string) => `/batches/${id}/validation` },
  { key: 'approvals', label: 'Approvals', icon: CheckCircle2, href: (id: string) => `/batches/${id}/approvals` },
  { key: 'reports', label: 'Reports', icon: Download, href: (id: string) => `/batches/${id}/reports` },
]

const ACTIVE_STATUSES = ['UPLOADED', 'PROCESSING']

export default function BatchDetailPage({ params }: Props) {
  const { id } = params
  const qc = useQueryClient()
  const [confirmCancel, setConfirmCancel] = useState(false)

  const { data: batch, isLoading } = useQuery({
    queryKey: ['batch', id],
    queryFn: () => getBatch(id),
    refetchInterval: (query) =>
      ACTIVE_STATUSES.includes(query.state.data?.status ?? '') ? 4000 : 30000,
  })

  // Lightweight status poll while processing — drives the progress bar
  const { data: status } = useQuery({
    queryKey: ['batch-status', id],
    queryFn: () => getBatchStatus(id),
    enabled: ACTIVE_STATUSES.includes(batch?.status ?? ''),
    refetchInterval: 2000,
  })

  const { data: validation } = useQuery({
    queryKey: ['validation', id],
    queryFn: () => listValidation(id),
    enabled: !!batch && !ACTIVE_STATUSES.includes(batch.status),
  })

  const cancelMut = useMutation({
    mutationFn: () => cancelBatch(id),
    onSuccess: () => {
      setConfirmCancel(false)
      qc.invalidateQueries({ queryKey: ['batch', id] })
      qc.invalidateQueries({ queryKey: ['batch-status', id] })
      qc.invalidateQueries({ queryKey: ['batches'] })
    },
  })

  if (isLoading) return <div className="p-8 text-gray-400">Loading batch...</div>
  if (!batch) return <div className="p-8 text-red-500">Batch not found</div>

  const isActive = ACTIVE_STATUSES.includes(batch.status)
  const isCancelled = batch.status === 'CANCELLED'

  return (
    <div className="p-8 max-w-6xl mx-auto space-y-6">
      <BatchSummaryCards batch={batch} />

      {/* Live progress bar while processing */}
      {isActive && status && (
        <div className="bg-blue-50 border border-blue-200 rounded-xl px-5 py-4 space-y-2">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2 text-blue-700 text-sm font-medium">
              <Loader2 className="w-4 h-4 animate-spin" />
              Processing… {status.done_files} / {status.total_files} files
            </div>
            <span className="text-blue-600 text-sm font-semibold">{status.progress_pct}%</span>
          </div>
          <ProgressBar value={status.progress_pct} color="blue" />
          <div className="flex gap-4 text-xs text-blue-600">
            {status.failed_files > 0 && <span className="text-red-500">{status.failed_files} failed</span>}
            {status.review_files > 0 && <span className="text-yellow-600">{status.review_files} needs review</span>}
          </div>
        </div>
      )}

      {/* Cancelled notice */}
      {isCancelled && (
        <div className="bg-gray-100 border border-gray-300 rounded-xl px-5 py-4 flex items-center gap-3">
          <StopCircle className="w-5 h-5 text-gray-500 shrink-0" />
          <p className="text-gray-600 text-sm">This batch was cancelled. Files processed so far are still available below.</p>
        </div>
      )}

      {/* Cancel button */}
      {isActive && (
        <div className="flex justify-end">
          {!confirmCancel ? (
            <button
              onClick={() => setConfirmCancel(true)}
              className="inline-flex items-center gap-2 bg-red-50 border border-red-300 text-red-700 hover:bg-red-100 px-4 py-2 rounded-lg text-sm font-medium transition-colors"
            >
              <StopCircle className="w-4 h-4" />
              Stop Processing
            </button>
          ) : (
            <div className="flex items-center gap-3 bg-red-50 border border-red-300 rounded-lg px-4 py-2">
              <span className="text-sm text-red-700 font-medium">Cancel this batch?</span>
              <button
                onClick={() => cancelMut.mutate()}
                disabled={cancelMut.isPending}
                className="bg-red-600 text-white text-xs px-3 py-1.5 rounded-lg hover:bg-red-700 disabled:opacity-50 font-medium"
              >
                {cancelMut.isPending ? 'Cancelling…' : 'Yes, Stop It'}
              </button>
              <button
                onClick={() => setConfirmCancel(false)}
                className="text-xs text-gray-500 hover:text-gray-700 px-2 py-1.5"
              >
                Keep Going
              </button>
            </div>
          )}
        </div>
      )}

      {/* Validation summary bar */}
      {validation && (validation.blocker_count > 0 || validation.error_count > 0) && (
        <div className="flex items-center gap-4 bg-red-50 border border-red-200 rounded-xl px-5 py-3">
          <AlertTriangle className="w-5 h-5 text-red-500 shrink-0" />
          <div className="flex gap-6 text-sm">
            {validation.blocker_count > 0 && (
              <span className="font-semibold text-red-700">{validation.blocker_count} Blockers</span>
            )}
            {validation.error_count > 0 && (
              <span className="text-red-600">{validation.error_count} Errors</span>
            )}
            {validation.warning_count > 0 && (
              <span className="text-yellow-700">{validation.warning_count} Warnings</span>
            )}
          </div>
          <Link href={`/batches/${id}/validation`} className="ml-auto text-sm text-red-600 underline font-medium">
            View Issues →
          </Link>
        </div>
      )}

      {/* Navigation tabs */}
      <div className="border-b border-gray-200">
        <nav className="flex gap-1">
          {TABS.map((tab) => {
            const Icon = tab.icon
            return (
              <Link
                key={tab.key}
                href={tab.href(id)}
                className="flex items-center gap-2 px-4 py-3 text-sm font-medium text-gray-500 hover:text-gray-800 hover:border-b-2 hover:border-blue-500 transition-all"
              >
                <Icon className="w-4 h-4" />
                {tab.label}
              </Link>
            )
          })}
        </nav>
      </div>

      <div className="bg-white rounded-xl border border-gray-200 p-6 text-center text-gray-400">
        <p className="text-sm">Select a tab above to view files, validation issues, approvals, or reports.</p>
      </div>
    </div>
  )
}
