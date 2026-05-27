'use client'
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useRouter } from 'next/navigation'
import Link from 'next/link'
import { listBatches, cancelBatch, deleteBatch } from '@/lib/api'
import StatusBadge from '@/components/ui/StatusBadge'
import { FolderOpen, Upload, StopCircle, Loader2, Trash2, AlertTriangle } from 'lucide-react'
import { formatDistanceToNow } from 'date-fns'

const ACTIVE_STATUSES = ['UPLOADED', 'PROCESSING']
const DELETABLE_STATUSES = ['NEEDS_REVIEW', 'PAYROLL_READY', 'COMPLETED', 'FAILED', 'CANCELLED']

type ConfirmAction = { type: 'cancel' | 'delete'; id: string } | null

export default function BatchesPage() {
  const router = useRouter()
  const qc = useQueryClient()
  const [confirm, setConfirm] = useState<ConfirmAction>(null)

  const { data, isLoading } = useQuery({
    queryKey: ['batches'],
    queryFn: () => listBatches({ limit: 50 }),
    refetchInterval: 6000,
  })

  const cancelMut = useMutation({
    mutationFn: (id: string) => cancelBatch(id),
    onSuccess: () => {
      setConfirm(null)
      qc.invalidateQueries({ queryKey: ['batches'] })
    },
  })

  const deleteMut = useMutation({
    mutationFn: (id: string) => deleteBatch(id),
    onSuccess: () => {
      setConfirm(null)
      qc.invalidateQueries({ queryKey: ['batches'] })
    },
  })

  const isPending = cancelMut.isPending || deleteMut.isPending

  return (
    <div className="p-8 max-w-6xl mx-auto">
      <div className="flex items-center justify-between mb-8">
        <div className="flex items-center gap-3">
          <FolderOpen className="w-7 h-7 text-blue-600" />
          <div>
            <h1 className="text-2xl font-bold text-gray-900">All Batches</h1>
            <p className="text-sm text-gray-500">{data?.total ?? 0} total batches</p>
          </div>
        </div>
        <Link href="/upload"
          className="inline-flex items-center gap-2 bg-blue-600 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-blue-700">
          <Upload className="w-4 h-4" /> New Upload
        </Link>
      </div>

      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        {isLoading ? (
          <div className="p-12 text-center text-gray-400">Loading...</div>
        ) : data?.items?.length === 0 ? (
          <div className="p-12 text-center text-gray-400">
            <FolderOpen className="w-10 h-10 mx-auto mb-3 opacity-40" />
            <p>No batches yet.</p>
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b border-gray-200">
              <tr>
                <th className="text-left px-6 py-3 text-xs font-medium text-gray-500 uppercase tracking-wider">Source File</th>
                <th className="text-left px-6 py-3 text-xs font-medium text-gray-500 uppercase tracking-wider">Status</th>
                <th className="text-left px-6 py-3 text-xs font-medium text-gray-500 uppercase tracking-wider">Period</th>
                <th className="text-right px-6 py-3 text-xs font-medium text-gray-500 uppercase tracking-wider">Files</th>
                <th className="text-right px-6 py-3 text-xs font-medium text-gray-500 uppercase tracking-wider">Ready</th>
                <th className="text-left px-6 py-3 text-xs font-medium text-gray-500 uppercase tracking-wider">Uploaded</th>
                <th className="px-6 py-3"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {data?.items?.map((b) => {
                const isActive = ACTIVE_STATUSES.includes(b.status)
                const isDeletable = DELETABLE_STATUSES.includes(b.status)
                const isConfirmingCancel = confirm?.type === 'cancel' && confirm.id === b.id
                const isConfirmingDelete = confirm?.type === 'delete' && confirm.id === b.id

                return (
                  <tr key={b.id} className="hover:bg-gray-50">
                    <td className="px-6 py-4">
                      <Link href={`/batches/${b.id}`} className="font-medium text-blue-600 hover:underline">
                        {b.source_name}
                      </Link>
                      <p className="text-xs text-gray-400">{b.id.slice(0, 8)}…</p>
                    </td>
                    <td className="px-6 py-4">
                      <div className="flex items-center gap-2">
                        {isActive && <Loader2 className="w-3.5 h-3.5 text-blue-500 animate-spin shrink-0" />}
                        <StatusBadge status={b.status} />
                      </div>
                    </td>
                    <td className="px-6 py-4 text-xs text-gray-500">
                      {b.filter_period_start
                        ? `${b.filter_period_start} → ${b.filter_period_end}`
                        : <span className="text-gray-300">—</span>}
                    </td>
                    <td className="px-6 py-4 text-right text-gray-700">{b.total_files}</td>
                    <td className="px-6 py-4 text-right text-green-600 font-medium">{b.payroll_ready_count}</td>
                    <td className="px-6 py-4 text-gray-500 text-xs">
                      {formatDistanceToNow(new Date(b.created_at), { addSuffix: true })}
                    </td>

                    {/* Actions column */}
                    <td className="px-6 py-4 text-right">
                      <div className="flex items-center justify-end gap-2">

                        {/* ── Stop (active batches) ── */}
                        {isActive && !isConfirmingCancel && (
                          <button
                            onClick={() => setConfirm({ type: 'cancel', id: b.id })}
                            title="Stop processing"
                            className="inline-flex items-center gap-1 text-xs text-red-500 hover:text-red-700 px-2 py-1 rounded hover:bg-red-50 transition-colors"
                          >
                            <StopCircle className="w-3.5 h-3.5" />
                            Stop
                          </button>
                        )}
                        {isConfirmingCancel && (
                          <div className="flex items-center gap-2">
                            <span className="text-xs text-red-600 font-medium">Stop batch?</span>
                            <button
                              onClick={() => cancelMut.mutate(b.id)}
                              disabled={isPending}
                              className="text-xs bg-red-600 text-white px-2 py-1 rounded hover:bg-red-700 disabled:opacity-50"
                            >
                              {isPending ? '…' : 'Yes'}
                            </button>
                            <button onClick={() => setConfirm(null)} className="text-xs text-gray-400 hover:text-gray-600">No</button>
                          </div>
                        )}

                        {/* ── Delete (finished batches) ── */}
                        {isDeletable && !isConfirmingDelete && (
                          <button
                            onClick={() => setConfirm({ type: 'delete', id: b.id })}
                            title="Delete batch"
                            className="inline-flex items-center gap-1 text-xs text-gray-400 hover:text-red-600 px-2 py-1 rounded hover:bg-red-50 transition-colors"
                          >
                            <Trash2 className="w-3.5 h-3.5" />
                            Delete
                          </button>
                        )}
                        {isConfirmingDelete && (
                          <div className="flex items-center gap-2 bg-red-50 border border-red-200 rounded-lg px-3 py-1.5">
                            <AlertTriangle className="w-3.5 h-3.5 text-red-500 shrink-0" />
                            <span className="text-xs text-red-700 font-medium">Delete permanently?</span>
                            <button
                              onClick={() => deleteMut.mutate(b.id)}
                              disabled={isPending}
                              className="text-xs bg-red-600 text-white px-2 py-1 rounded hover:bg-red-700 disabled:opacity-50 font-medium"
                            >
                              {isPending ? '…' : 'Delete'}
                            </button>
                            <button onClick={() => setConfirm(null)} className="text-xs text-gray-500 hover:text-gray-700">Cancel</button>
                          </div>
                        )}

                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
