'use client'
import { useState, useCallback } from 'react'
import { useRouter } from 'next/navigation'
import { useDropzone } from 'react-dropzone'
import { useQuery, useMutation } from '@tanstack/react-query'
import { uploadZip, listPayrollPeriods } from '@/lib/api'
import { Upload, FileArchive, CheckCircle2, AlertCircle } from 'lucide-react'
import ProgressBar from '@/components/ui/ProgressBar'

export default function UploadPage() {
  const router = useRouter()
  const [file, setFile] = useState<File | null>(null)
  const [periodId, setPeriodId] = useState('')
  const [notes, setNotes] = useState('')
  const [progress, setProgress] = useState(0)
  const [error, setError] = useState('')

  const { data: periods } = useQuery({ queryKey: ['payroll-periods'], queryFn: listPayrollPeriods })

  const mutation = useMutation({
    mutationFn: () => uploadZip(file!, periodId || undefined, notes || undefined, setProgress),
    onSuccess: (data) => {
      router.push(`/batches/${data.batch_id}`)
    },
    onError: (err: Error) => {
      setError(err.message || 'Upload failed')
    },
  })

  const onDrop = useCallback((accepted: File[]) => {
    setFile(accepted[0] || null)
    setError('')
  }, [])

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: { 'application/zip': ['.zip'] },
    maxFiles: 1,
  })

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!file) { setError('Please select a ZIP file'); return }
    mutation.mutate()
  }

  return (
    <div className="p-8 max-w-2xl mx-auto">
      <div className="flex items-center gap-3 mb-8">
        <Upload className="w-7 h-7 text-blue-600" />
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Upload Timesheets</h1>
          <p className="text-sm text-gray-500">Upload a ZIP file containing employee timesheets</p>
        </div>
      </div>

      <form onSubmit={handleSubmit} className="space-y-6">
        {/* Payroll period */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1.5">Payroll Period</label>
          <select
            value={periodId}
            onChange={(e) => setPeriodId(e.target.value)}
            className="w-full border border-gray-300 rounded-lg px-3 py-2.5 text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
          >
            <option value="">— Select period (optional) —</option>
            {periods?.items?.map((p) => (
              <option key={p.id} value={p.id}>{p.period_key} ({p.start_date} → {p.end_date})</option>
            ))}
          </select>
        </div>

        {/* Drop zone */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1.5">ZIP File</label>
          <div
            {...getRootProps()}
            className={`border-2 border-dashed rounded-xl p-10 text-center cursor-pointer transition-colors ${
              isDragActive ? 'border-blue-400 bg-blue-50' : 'border-gray-300 hover:border-blue-300 hover:bg-gray-50'
            }`}
          >
            <input {...getInputProps()} />
            {file ? (
              <div className="flex flex-col items-center gap-2">
                <FileArchive className="w-10 h-10 text-blue-500" />
                <p className="font-medium text-gray-800">{file.name}</p>
                <p className="text-xs text-gray-500">{(file.size / 1024 / 1024).toFixed(1)} MB</p>
              </div>
            ) : (
              <div className="flex flex-col items-center gap-2 text-gray-400">
                <Upload className="w-10 h-10" />
                <p className="text-sm">{isDragActive ? 'Drop it here' : 'Drag & drop a ZIP file, or click to browse'}</p>
                <p className="text-xs">Maximum size: 2 GB</p>
              </div>
            )}
          </div>
        </div>

        {/* Notes */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1.5">Notes (optional)</label>
          <textarea
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            rows={2}
            placeholder="e.g. April 2026 payroll batch"
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm resize-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
          />
        </div>

        {/* Error */}
        {error && (
          <div className="flex items-center gap-2 text-red-600 bg-red-50 border border-red-200 rounded-lg px-4 py-3 text-sm">
            <AlertCircle className="w-4 h-4 shrink-0" />
            {error}
          </div>
        )}

        {/* Upload progress */}
        {mutation.isPending && (
          <ProgressBar value={progress} label="Uploading..." color="blue" />
        )}

        {/* Submit */}
        <button
          type="submit"
          disabled={mutation.isPending || !file}
          className="w-full bg-blue-600 text-white font-medium py-3 rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center justify-center gap-2"
        >
          {mutation.isPending ? (
            <><span className="animate-spin inline-block w-4 h-4 border-2 border-white border-t-transparent rounded-full" /> Processing...</>
          ) : (
            <><Upload className="w-4 h-4" /> Upload & Process</>
          )}
        </button>
      </form>
    </div>
  )
}
