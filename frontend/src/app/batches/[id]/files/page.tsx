'use client'
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { listFiles, markNonTimesheet, reprocessFile, getRawExtraction, previewFileUrl } from '@/lib/api'
import StatusBadge from '@/components/ui/StatusBadge'
import { FileText, Eye, RefreshCw, Ban, ExternalLink, X } from 'lucide-react'

interface Props { params: { id: string } }

export default function FilesPage({ params }: Props) {
  const { id: batchId } = params
  const qc = useQueryClient()
  const [rawExtModal, setRawExtModal] = useState<string | null>(null)
  const [rawData, setRawData] = useState<unknown>(null)
  const [previewFile, setPreviewFile] = useState<{ id: string; name: string; ext: string } | null>(null)

  const { data, isLoading } = useQuery({
    queryKey: ['files', batchId],
    queryFn: () => listFiles(batchId, { limit: 200 }),
  })

  const reprocessMut = useMutation({
    mutationFn: (fileId: string) => reprocessFile(fileId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['files', batchId] }),
  })

  const nonTsMut = useMutation({
    mutationFn: (fileId: string) => markNonTimesheet(fileId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['files', batchId] }),
  })

  const viewRaw = async (fileId: string) => {
    try {
      const data = await getRawExtraction(fileId)
      setRawData(data)
      setRawExtModal(fileId)
    } catch {
      alert('No raw extraction available for this file yet.')
    }
  }

  const previewable = (ext: string | undefined) => ['.pdf', '.png', '.jpg', '.jpeg', '.tiff', '.tif'].includes((ext ?? '').toLowerCase())

  return (
    <div className="p-6 max-w-7xl mx-auto">
      <div className="flex items-center gap-2 mb-6">
        <FileText className="w-5 h-5 text-blue-600" />
        <h2 className="text-lg font-semibold text-gray-900">File Inventory</h2>
        <span className="text-sm text-gray-400">({data?.total ?? 0} files)</span>
      </div>

      {isLoading ? (
        <div className="text-center py-12 text-gray-400">Loading files...</div>
      ) : (
        <div className="bg-white rounded-xl border border-gray-200 overflow-x-auto">
          <table className="w-full text-xs">
            <thead className="bg-gray-50 border-b border-gray-200">
              <tr>
                {['Folder', 'File Name', 'Ext', 'Employee', 'Match', 'OCR', 'Dup', 'Status', 'Actions'].map((h) => (
                  <th key={h} className="text-left px-3 py-3 text-gray-500 font-medium uppercase tracking-wider whitespace-nowrap">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {data?.items?.map((f) => (
                <tr key={f.id} className={`hover:bg-gray-50 ${f.is_duplicate || f.processing_status === 'FAILED' ? 'bg-red-50' : f.processing_status === 'NEEDS_REVIEW' ? 'bg-yellow-50' : ''}`}>
                  <td className="px-3 py-2.5 text-gray-400 max-w-[120px] truncate">{f.folder_path || '/'}</td>
                  <td className="px-3 py-2.5 font-medium text-gray-800 max-w-[160px] truncate" title={f.file_name}>{f.file_name}</td>
                  <td className="px-3 py-2.5 text-gray-500">{f.file_ext}</td>
                  <td className="px-3 py-2.5 text-gray-700 max-w-[120px] truncate" title={f.detected_employee_name ?? ''}>{f.detected_employee_name || '—'}</td>
                  <td className="px-3 py-2.5"><StatusBadge status={f.match_status} /></td>
                  <td className="px-3 py-2.5">{f.ocr_required ? <span className="text-purple-600 font-medium">Yes</span> : 'No'}</td>
                  <td className="px-3 py-2.5">{f.is_duplicate ? <span className="text-orange-600 font-medium">Yes</span> : 'No'}</td>
                  <td className="px-3 py-2.5"><StatusBadge status={f.processing_status} /></td>
                  <td className="px-3 py-2.5">
                    <div className="flex items-center gap-1">
                      {/* Preview original file */}
                      {previewable(f.file_ext) ? (
                        <button
                          onClick={() => setPreviewFile({ id: f.id, name: f.file_name, ext: f.file_ext ?? '' })}
                          title="Preview file"
                          className="p-1 rounded hover:bg-indigo-100 text-indigo-500 transition-colors"
                        >
                          <Eye className="w-3.5 h-3.5" />
                        </button>
                      ) : (
                        <a
                          href={previewFileUrl(f.id)}
                          target="_blank"
                          rel="noopener noreferrer"
                          title="Open file"
                          className="p-1 rounded hover:bg-indigo-100 text-indigo-500 transition-colors"
                        >
                          <ExternalLink className="w-3.5 h-3.5" />
                        </a>
                      )}
                      {/* Raw extraction JSON */}
                      <button onClick={() => viewRaw(f.id)} title="View raw extraction"
                        className="p-1 rounded hover:bg-blue-100 text-blue-500 transition-colors">
                        <FileText className="w-3.5 h-3.5" />
                      </button>
                      <button onClick={() => reprocessMut.mutate(f.id)} title="Reprocess"
                        className="p-1 rounded hover:bg-green-100 text-green-500 transition-colors">
                        <RefreshCw className="w-3.5 h-3.5" />
                      </button>
                      <button onClick={() => nonTsMut.mutate(f.id)} title="Mark non-timesheet"
                        className="p-1 rounded hover:bg-gray-100 text-gray-400 transition-colors">
                        <Ban className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* File preview modal */}
      {previewFile && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-xl w-full max-w-4xl max-h-[90vh] flex flex-col shadow-2xl">
            <div className="flex items-center justify-between px-5 py-3 border-b border-gray-200 shrink-0">
              <div className="flex items-center gap-2 text-sm font-medium text-gray-800 truncate">
                <FileText className="w-4 h-4 text-blue-500 shrink-0" />
                <span className="truncate">{previewFile.name}</span>
              </div>
              <div className="flex items-center gap-3 ml-4 shrink-0">
                <a
                  href={previewFileUrl(previewFile.id)}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-xs text-blue-600 hover:underline flex items-center gap-1"
                >
                  <ExternalLink className="w-3.5 h-3.5" /> Open in tab
                </a>
                <button onClick={() => setPreviewFile(null)} className="text-gray-400 hover:text-gray-700">
                  <X className="w-5 h-5" />
                </button>
              </div>
            </div>
            <div className="flex-1 overflow-hidden">
              <iframe
                src={previewFileUrl(previewFile.id)}
                className="w-full h-full border-0 min-h-[70vh]"
                title={previewFile.name}
              />
            </div>
          </div>
        </div>
      )}

      {/* Raw extraction modal */}
      {rawExtModal && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-xl max-w-3xl w-full max-h-[80vh] overflow-auto">
            <div className="flex items-center justify-between px-6 py-4 border-b">
              <h3 className="font-semibold text-gray-900">Raw Extraction</h3>
              <button onClick={() => setRawExtModal(null)} className="text-gray-400 hover:text-gray-700 text-xl leading-none">×</button>
            </div>
            <pre className="px-6 py-4 text-xs text-gray-700 whitespace-pre-wrap break-words">
              {JSON.stringify(rawData, null, 2)}
            </pre>
          </div>
        </div>
      )}
    </div>
  )
}
