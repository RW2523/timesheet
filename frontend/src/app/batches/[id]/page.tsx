'use client'
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { getBatch, getBatchStatus, getBatchStats, cancelBatch, deleteBatch, listValidation, listReports, downloadReportUrl } from '@/lib/api'
import BatchSummaryCards from '@/components/BatchSummaryCards'
import { FileText, AlertTriangle, CheckCircle2, Download, StopCircle, Loader2, Calendar, FileSpreadsheet, Trash2 } from 'lucide-react'
import ProgressBar from '@/components/ui/ProgressBar'

interface Props { params: { id: string } }

const TABS = [
  { key: 'files', label: 'Files', icon: FileText, href: (id: string) => `/batches/${id}/files` },
  { key: 'calendar', label: 'Calendar', icon: Calendar, href: (id: string) => `/batches/${id}/calendar` },
  { key: 'validation', label: 'Validation Issues', icon: AlertTriangle, href: (id: string) => `/batches/${id}/validation` },
  { key: 'approvals', label: 'Approvals', icon: CheckCircle2, href: (id: string) => `/batches/${id}/approvals` },
  { key: 'reports', label: 'Reports', icon: Download, href: (id: string) => `/batches/${id}/reports` },
]

const ACTIVE_STATUSES = ['UPLOADED', 'PROCESSING']
const DELETABLE_STATUSES = ['NEEDS_REVIEW', 'PAYROLL_READY', 'COMPLETED', 'FAILED', 'CANCELLED']

export default function BatchDetailPage({ params }: Props) {
  const { id } = params
  const router = useRouter()
  const qc = useQueryClient()
  const [confirmCancel, setConfirmCancel] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)

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

  // Extra stats (OCR, matched, unmatched, extraction failed, non-timesheet)
  const { data: extraStats } = useQuery({
    queryKey: ['batch-stats', id],
    queryFn: () => getBatchStats(id),
    enabled: !!batch && !ACTIVE_STATUSES.includes(batch.status),
    refetchInterval: false,
  })

  const { data: validation } = useQuery({
    queryKey: ['validation', id],
    queryFn: () => listValidation(id),
    enabled: !!batch && !ACTIVE_STATUSES.includes(batch.status),
  })

  const { data: reports } = useQuery({
    queryKey: ['reports', id],
    queryFn: () => listReports(id),
    enabled: !!batch && !ACTIVE_STATUSES.includes(batch.status),
    refetchInterval: 30000,
  })

  // Find the summary CSV report if available
  const summaryCSV = reports?.items?.find((r: { report_type: string; id: string }) => r.report_type === 'SUMMARY_CSV')

  const cancelMut = useMutation({
    mutationFn: () => cancelBatch(id),
    onSuccess: () => {
      setConfirmCancel(false)
      qc.invalidateQueries({ queryKey: ['batch', id] })
      qc.invalidateQueries({ queryKey: ['batch-status', id] })
      qc.invalidateQueries({ queryKey: ['batches'] })
    },
  })

  const deleteMut = useMutation({
    mutationFn: () => deleteBatch(id),
    onSuccess: () => {
      router.push('/batches')
    },
  })

  if (isLoading) return <div className="p-8 text-gray-400">Loading batch...</div>
  if (!batch) return <div className="p-8 text-red-500">Batch not found</div>

  const isActive = ACTIVE_STATUSES.includes(batch.status)
  const isCancelled = batch.status === 'CANCELLED'

  return (
    <div className="p-8 max-w-6xl mx-auto space-y-6">
      <BatchSummaryCards batch={batch} extraStats={extraStats ?? null} />

      {/* Period filter banner */}
      {(batch.filter_period_start || batch.filter_period_end) && (
        <div className="flex items-center gap-3 bg-indigo-50 border border-indigo-200 rounded-xl px-5 py-3 text-sm text-indigo-700">
          <Calendar className="w-4 h-4 shrink-0" />
          <span>Period filter: <strong>{batch.filter_period_start}</strong> → <strong>{batch.filter_period_end}</strong></span>
          {summaryCSV && (
            <a
              href={downloadReportUrl(summaryCSV.id)}
              target="_blank"
              rel="noopener noreferrer"
              className="ml-auto flex items-center gap-2 bg-indigo-600 hover:bg-indigo-700 text-white text-xs font-medium px-3 py-1.5 rounded-lg transition-colors"
            >
              <FileSpreadsheet className="w-3.5 h-3.5" />
              Download Summary CSV
            </a>
          )}
        </div>
      )}

      {/* Summary CSV download (always show when ready) */}
      {!batch.filter_period_start && summaryCSV && (
        <div className="flex items-center gap-3 bg-green-50 border border-green-200 rounded-xl px-5 py-3 text-sm">
          <FileSpreadsheet className="w-4 h-4 text-green-600 shrink-0" />
          <span className="text-green-700">Summary CSV ready</span>
          <a
            href={downloadReportUrl(summaryCSV.id)}
            target="_blank"
            rel="noopener noreferrer"
            className="ml-auto flex items-center gap-2 bg-green-600 hover:bg-green-700 text-white text-xs font-medium px-3 py-1.5 rounded-lg transition-colors"
          >
            <Download className="w-3.5 h-3.5" />
            Download All-Employee CSV
          </a>
        </div>
      )}

      {/* Live progress bar while processing */}
      {isActive && status && (
        <div className="bg-blue-50 border border-blue-200 rounded-xl px-5 py-4 space-y-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2 text-blue-700 text-sm font-medium">
              <Loader2 className="w-4 h-4 animate-spin" />
              {status.current_stage || 'Processing…'}
            </div>
            <span className="text-blue-600 text-sm font-semibold">{status.progress_pct}%</span>
          </div>
          <ProgressBar value={status.progress_pct} color="blue" />
          {status.current_file && (
            <div className="text-xs text-blue-600 bg-blue-100 rounded-lg px-3 py-1.5 flex items-center gap-2 truncate">
              <span className="shrink-0 font-medium">Current file:</span>
              <span className="truncate">{status.current_file}</span>
            </div>
          )}
          <div className="flex gap-4 text-xs text-blue-600">
            <span>{status.done_files} / {status.total_files} files completed</span>
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

      {/* Delete button (finished batches) */}
      {DELETABLE_STATUSES.includes(batch.status) && (
        <div className="flex justify-end">
          {!confirmDelete ? (
            <button
              onClick={() => setConfirmDelete(true)}
              className="inline-flex items-center gap-2 text-gray-400 hover:text-red-600 hover:bg-red-50 border border-transparent hover:border-red-200 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors"
            >
              <Trash2 className="w-3.5 h-3.5" />
              Delete Batch
            </button>
          ) : (
            <div className="flex items-center gap-3 bg-red-50 border border-red-300 rounded-lg px-4 py-2">
              <span className="text-sm text-red-700 font-medium">Delete this batch permanently?</span>
              <span className="text-xs text-red-500">All files, extractions and reports will be removed.</span>
              <button
                onClick={() => deleteMut.mutate()}
                disabled={deleteMut.isPending}
                className="bg-red-600 text-white text-xs px-3 py-1.5 rounded-lg hover:bg-red-700 disabled:opacity-50 font-medium"
              >
                {deleteMut.isPending ? 'Deleting…' : 'Yes, Delete'}
              </button>
              <button
                onClick={() => setConfirmDelete(false)}
                className="text-xs text-gray-500 hover:text-gray-700 px-2 py-1.5"
              >
                Cancel
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
