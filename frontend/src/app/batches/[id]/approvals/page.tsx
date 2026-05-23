'use client'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { listApprovals, updateApproval } from '@/lib/api'
import StatusBadge from '@/components/ui/StatusBadge'
import { CheckCircle2, XCircle } from 'lucide-react'

interface Props { params: { id: string } }

export default function ApprovalsPage({ params }: Props) {
  const { id: batchId } = params
  const qc = useQueryClient()

  const { data, isLoading } = useQuery({
    queryKey: ['approvals', batchId],
    queryFn: () => listApprovals(batchId),
  })

  const approveMut = useMutation({
    mutationFn: ({ subId, status }: { subId: string; status: string }) =>
      updateApproval(subId, { approval_status: status }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['approvals', batchId] }),
  })

  return (
    <div className="p-6 max-w-5xl mx-auto">
      <div className="flex items-center gap-2 mb-6">
        <CheckCircle2 className="w-5 h-5 text-green-500" />
        <h2 className="text-lg font-semibold text-gray-900">Approvals</h2>
        <span className="text-sm text-gray-400">({data?.total ?? 0} submissions)</span>
      </div>

      {isLoading ? (
        <div className="text-center py-12 text-gray-400">Loading...</div>
      ) : (
        <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b">
              <tr>
                {['Submission ID', 'Employee ID', 'Approved By', 'Status', 'Actions'].map((h) => (
                  <th key={h} className="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {data?.items?.map((a: Record<string, string>) => (
                <tr key={a.submission_id} className="hover:bg-gray-50">
                  <td className="px-4 py-3 text-xs text-gray-500">{String(a.submission_id).slice(0, 8)}…</td>
                  <td className="px-4 py-3 text-xs text-gray-500">{String(a.employee_id || '').slice(0, 8)}…</td>
                  <td className="px-4 py-3 text-gray-700">{a.approved_by_name || '—'}</td>
                  <td className="px-4 py-3"><StatusBadge status={a.approval_status} /></td>
                  <td className="px-4 py-3">
                    {a.approval_status === 'PENDING' && (
                      <div className="flex items-center gap-2">
                        <button
                          onClick={() => approveMut.mutate({ subId: a.submission_id, status: 'APPROVED' })}
                          className="inline-flex items-center gap-1 text-xs bg-green-100 text-green-700 px-3 py-1 rounded-lg hover:bg-green-200"
                        >
                          <CheckCircle2 className="w-3 h-3" /> Approve
                        </button>
                        <button
                          onClick={() => approveMut.mutate({ subId: a.submission_id, status: 'REJECTED' })}
                          className="inline-flex items-center gap-1 text-xs bg-red-100 text-red-700 px-3 py-1 rounded-lg hover:bg-red-200"
                        >
                          <XCircle className="w-3 h-3" /> Reject
                        </button>
                      </div>
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
