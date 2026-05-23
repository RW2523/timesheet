'use client'
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { listValidation, resolveValidationError } from '@/lib/api'
import SeverityBadge from '@/components/ui/SeverityBadge'
import StatusBadge from '@/components/ui/StatusBadge'
import { AlertTriangle, CheckCircle2, Filter } from 'lucide-react'

interface Props { params: { id: string } }

const SEVERITY_ORDER = ['BLOCKER', 'ERROR', 'WARNING', 'INFO']

export default function ValidationPage({ params }: Props) {
  const { id: batchId } = params
  const qc = useQueryClient()
  const [severityFilter, setSeverityFilter] = useState('')
  const [statusFilter, setStatusFilter] = useState('OPEN')

  const { data, isLoading } = useQuery({
    queryKey: ['validation', batchId, severityFilter, statusFilter],
    queryFn: () => listValidation(batchId, {
      severity: severityFilter || undefined,
      status: statusFilter || undefined,
      limit: 200,
    }),
  })

  const resolveMut = useMutation({
    mutationFn: (id: string) => resolveValidationError(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['validation', batchId] }),
  })

  return (
    <div className="p-6 max-w-7xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-2">
          <AlertTriangle className="w-5 h-5 text-yellow-500" />
          <h2 className="text-lg font-semibold text-gray-900">Validation Issues</h2>
        </div>

        {/* Summary counts */}
        {data && (
          <div className="flex items-center gap-4 text-sm">
            {data.blocker_count > 0 && <span className="text-red-600 font-semibold">{data.blocker_count} Blockers</span>}
            {data.error_count > 0 && <span className="text-red-500">{data.error_count} Errors</span>}
            {data.warning_count > 0 && <span className="text-yellow-600">{data.warning_count} Warnings</span>}
            {data.info_count > 0 && <span className="text-blue-500">{data.info_count} Info</span>}
          </div>
        )}
      </div>

      {/* Filters */}
      <div className="flex gap-3 mb-4">
        <select value={severityFilter} onChange={(e) => setSeverityFilter(e.target.value)}
          className="border border-gray-200 rounded-lg px-3 py-2 text-sm">
          <option value="">All Severities</option>
          {SEVERITY_ORDER.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
        <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}
          className="border border-gray-200 rounded-lg px-3 py-2 text-sm">
          <option value="OPEN">Open</option>
          <option value="RESOLVED">Resolved</option>
          <option value="">All</option>
        </select>
      </div>

      {isLoading ? (
        <div className="text-center py-12 text-gray-400">Loading...</div>
      ) : data?.items?.length === 0 ? (
        <div className="bg-green-50 rounded-xl border border-green-200 p-12 text-center">
          <CheckCircle2 className="w-10 h-10 text-green-500 mx-auto mb-3" />
          <p className="text-green-700 font-medium">No validation issues found!</p>
        </div>
      ) : (
        <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b border-gray-200">
              <tr>
                {['Severity', 'Rule', 'Employee', 'Message', 'Expected', 'Actual', 'Action Required', 'Status', ''].map((h) => (
                  <th key={h} className="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase tracking-wider whitespace-nowrap">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {data?.items?.map((e) => (
                <tr key={e.id} className={e.severity === 'BLOCKER' || e.severity === 'ERROR' ? 'bg-red-50' : e.severity === 'WARNING' ? 'bg-yellow-50' : ''}>
                  <td className="px-4 py-3"><SeverityBadge severity={e.severity} /></td>
                  <td className="px-4 py-3 font-mono text-xs text-gray-700">{e.rule_code}</td>
                  <td className="px-4 py-3 text-gray-500 text-xs max-w-[80px] truncate">{e.employee_id ? e.employee_id.slice(0, 8) + '…' : '—'}</td>
                  <td className="px-4 py-3 text-gray-800 max-w-[220px]">{e.message}</td>
                  <td className="px-4 py-3 text-gray-500 text-xs">{e.expected_value || '—'}</td>
                  <td className="px-4 py-3 text-gray-500 text-xs">{e.actual_value || '—'}</td>
                  <td className="px-4 py-3 text-orange-700 text-xs max-w-[160px]">{e.action_required || '—'}</td>
                  <td className="px-4 py-3"><StatusBadge status={e.status} /></td>
                  <td className="px-4 py-3">
                    {e.status === 'OPEN' && (
                      <button
                        onClick={() => resolveMut.mutate(e.id)}
                        className="text-xs text-green-600 hover:text-green-800 font-medium"
                      >
                        Resolve
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
