'use client'
import { useQuery } from '@tanstack/react-query'
import Link from 'next/link'
import { getDashboard, listBatches } from '@/lib/api'
import StatusBadge from '@/components/ui/StatusBadge'
import {
  LayoutDashboard, Upload, AlertOctagon, CheckCircle2, FolderOpen,
  AlertTriangle, Clock,
} from 'lucide-react'
import { formatDistanceToNow } from 'date-fns'

export default function DashboardPage() {
  const { data: stats } = useQuery({ queryKey: ['dashboard'], queryFn: getDashboard, refetchInterval: 10000 })
  const { data: batches } = useQuery({ queryKey: ['batches'], queryFn: () => listBatches({ limit: 10 }) })

  return (
    <div className="p-8 max-w-6xl mx-auto">
      <div className="flex items-center gap-3 mb-8">
        <LayoutDashboard className="w-7 h-7 text-blue-600" />
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Dashboard</h1>
          <p className="text-sm text-gray-500">Timesheet processing overview</p>
        </div>
      </div>

      {/* Stats cards */}
      {stats && (
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4 mb-8">
          <StatCard label="Total Batches" value={stats.total_batches} icon={<FolderOpen />} color="gray" />
          <StatCard label="Processing" value={stats.processing_batches} icon={<Clock />} color="blue" />
          <StatCard label="Needs Review" value={stats.needs_review_batches} icon={<AlertTriangle />} color="yellow" />
          <StatCard label="Payroll Ready" value={stats.payroll_ready_batches} icon={<CheckCircle2 />} color="green" />
          <StatCard label="Failed" value={stats.failed_batches} icon={<AlertOctagon />} color="red" />
          <StatCard label="Open Blockers" value={stats.open_blockers} icon={<AlertOctagon />} color="red" />
          <StatCard label="Open Warnings" value={stats.open_warnings} icon={<AlertTriangle />} color="yellow" />
        </div>
      )}

      {/* Quick actions */}
      <div className="flex gap-3 mb-8">
        <Link href="/upload"
          className="inline-flex items-center gap-2 bg-blue-600 text-white px-5 py-2.5 rounded-lg text-sm font-medium hover:bg-blue-700 transition-colors">
          <Upload className="w-4 h-4" />
          Upload ZIP
        </Link>
      </div>

      {/* Recent batches */}
      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        <div className="px-6 py-4 border-b border-gray-100 flex items-center justify-between">
          <h2 className="font-semibold text-gray-900">Recent Batches</h2>
          <Link href="/batches" className="text-sm text-blue-600 hover:underline">View all</Link>
        </div>
        {batches?.items?.length === 0 ? (
          <div className="px-6 py-12 text-center text-gray-400">
            <FolderOpen className="w-10 h-10 mx-auto mb-3 opacity-40" />
            <p>No batches yet. Upload a ZIP to get started.</p>
          </div>
        ) : (
          <div className="divide-y divide-gray-100">
            {batches?.items?.map((b) => (
              <Link key={b.id} href={`/batches/${b.id}`}
                className="flex items-center px-6 py-4 hover:bg-gray-50 transition-colors">
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-gray-900 truncate">{b.source_name}</p>
                  <p className="text-xs text-gray-400 mt-0.5">
                    {formatDistanceToNow(new Date(b.created_at), { addSuffix: true })}
                  </p>
                </div>
                <div className="flex items-center gap-4 ml-4">
                  <span className="text-xs text-gray-500">{b.total_files} files</span>
                  <StatusBadge status={b.status} />
                </div>
              </Link>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

function StatCard({ label, value, icon, color }: { label: string; value: number; icon: React.ReactNode; color: string }) {
  const border = { gray: 'border-l-gray-300', blue: 'border-l-blue-400', green: 'border-l-green-400', yellow: 'border-l-yellow-400', red: 'border-l-red-400' }
  const text = { gray: 'text-gray-500', blue: 'text-blue-500', green: 'text-green-500', yellow: 'text-yellow-500', red: 'text-red-500' }
  return (
    <div className={`bg-white rounded-xl border border-gray-200 border-l-4 ${border[color as keyof typeof border]} p-4`}>
      <div className={`${text[color as keyof typeof text]} mb-2 [&>svg]:w-5 [&>svg]:h-5`}>{icon}</div>
      <p className="text-2xl font-bold text-gray-800">{value.toLocaleString()}</p>
      <p className="text-xs text-gray-500 mt-0.5">{label}</p>
    </div>
  )
}
