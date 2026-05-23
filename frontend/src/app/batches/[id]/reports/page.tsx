'use client'
import { useQuery, useMutation } from '@tanstack/react-query'
import { listReports, generateReport, downloadReportUrl } from '@/lib/api'
import { Download, FileSpreadsheet, RefreshCw } from 'lucide-react'
import { formatDistanceToNow } from 'date-fns'

interface Props { params: { id: string } }

export default function ReportsPage({ params }: Props) {
  const { id: batchId } = params

  const { data, isLoading, refetch } = useQuery({
    queryKey: ['reports', batchId],
    queryFn: () => listReports(batchId),
  })

  const genMut = useMutation({
    mutationFn: () => generateReport(batchId),
    onSuccess: () => refetch(),
  })

  return (
    <div className="p-6 max-w-4xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-2">
          <FileSpreadsheet className="w-5 h-5 text-blue-600" />
          <h2 className="text-lg font-semibold text-gray-900">Generated Reports</h2>
        </div>
        <button
          onClick={() => genMut.mutate()}
          disabled={genMut.isPending}
          className="inline-flex items-center gap-2 bg-blue-600 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-50"
        >
          {genMut.isPending
            ? <><span className="animate-spin w-4 h-4 border-2 border-white border-t-transparent rounded-full inline-block" /> Generating...</>
            : <><RefreshCw className="w-4 h-4" /> Generate Report</>
          }
        </button>
      </div>

      {isLoading ? (
        <div className="text-center py-12 text-gray-400">Loading...</div>
      ) : data?.items?.length === 0 ? (
        <div className="bg-gray-50 rounded-xl border border-gray-200 p-12 text-center">
          <FileSpreadsheet className="w-10 h-10 text-gray-300 mx-auto mb-3" />
          <p className="text-gray-500">No reports generated yet.</p>
          <p className="text-sm text-gray-400 mt-1">Click "Generate Report" to create an 8-sheet Excel workbook.</p>
        </div>
      ) : (
        <div className="space-y-3">
          {data?.items?.map((r) => (
            <div key={r.id} className="bg-white border border-gray-200 rounded-xl px-5 py-4 flex items-center">
              <FileSpreadsheet className="w-8 h-8 text-green-500 shrink-0 mr-4" />
              <div className="flex-1 min-w-0">
                <p className="font-medium text-gray-900 truncate">{r.file_name}</p>
                <p className="text-xs text-gray-400 mt-0.5">
                  {r.report_type} · {formatDistanceToNow(new Date(r.created_at), { addSuffix: true })}
                </p>
              </div>
              <a
                href={downloadReportUrl(r.id)}
                download={r.file_name}
                className="inline-flex items-center gap-2 bg-green-600 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-green-700 transition-colors shrink-0 ml-4"
              >
                <Download className="w-4 h-4" />
                Download
              </a>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
