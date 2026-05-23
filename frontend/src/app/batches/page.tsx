'use client'
import { useQuery } from '@tanstack/react-query'
import Link from 'next/link'
import { listBatches } from '@/lib/api'
import StatusBadge from '@/components/ui/StatusBadge'
import { FolderOpen, Upload } from 'lucide-react'
import { formatDistanceToNow } from 'date-fns'

export default function BatchesPage() {
  const { data, isLoading } = useQuery({ queryKey: ['batches'], queryFn: () => listBatches({ limit: 50 }), refetchInterval: 8000 })

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
                <th className="text-right px-6 py-3 text-xs font-medium text-gray-500 uppercase tracking-wider">Files</th>
                <th className="text-right px-6 py-3 text-xs font-medium text-gray-500 uppercase tracking-wider">Ready</th>
                <th className="text-left px-6 py-3 text-xs font-medium text-gray-500 uppercase tracking-wider">Uploaded</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {data?.items?.map((b) => (
                <tr key={b.id} className="hover:bg-gray-50">
                  <td className="px-6 py-4">
                    <Link href={`/batches/${b.id}`} className="font-medium text-blue-600 hover:underline">
                      {b.source_name}
                    </Link>
                    <p className="text-xs text-gray-400">{b.id.slice(0, 8)}…</p>
                  </td>
                  <td className="px-6 py-4"><StatusBadge status={b.status} /></td>
                  <td className="px-6 py-4 text-right text-gray-700">{b.total_files}</td>
                  <td className="px-6 py-4 text-right text-green-600 font-medium">{b.payroll_ready_count}</td>
                  <td className="px-6 py-4 text-gray-500 text-xs">
                    {formatDistanceToNow(new Date(b.created_at), { addSuffix: true })}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
