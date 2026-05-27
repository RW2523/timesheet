'use client'
import { useState, useCallback } from 'react'
import { useRouter } from 'next/navigation'
import { useDropzone } from 'react-dropzone'
import { useQuery, useMutation } from '@tanstack/react-query'
import { uploadZip, listPayrollPeriods } from '@/lib/api'
import { Upload, FileArchive, AlertCircle, Calendar, ChevronDown } from 'lucide-react'
import ProgressBar from '@/components/ui/ProgressBar'

const MONTHS = [
  'January','February','March','April','May','June',
  'July','August','September','October','November','December',
]

function getDefaultPeriod() {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
}

export default function UploadPage() {
  const router = useRouter()
  const [file, setFile] = useState<File | null>(null)
  const [periodType, setPeriodType] = useState<'month' | 'year' | 'custom' | 'all'>('month')
  const [periodMonth, setPeriodMonth] = useState(getDefaultPeriod())
  const [periodYear, setPeriodYear] = useState(String(new Date().getFullYear()))
  const [customStart, setCustomStart] = useState('')
  const [customEnd, setCustomEnd] = useState('')
  const [notes, setNotes] = useState('')
  const [progress, setProgress] = useState(0)
  const [error, setError] = useState('')

  const currentYear = new Date().getFullYear()
  const years = Array.from({ length: 5 }, (_, i) => String(currentYear - i))

  function getPeriodValue() {
    if (periodType === 'month') return periodMonth
    if (periodType === 'year') return periodYear
    if (periodType === 'custom') return `${customStart}:${customEnd}`
    return ''
  }

  const mutation = useMutation({
    mutationFn: () => uploadZip(
      file!,
      undefined,
      notes || undefined,
      setProgress,
      periodType,
      getPeriodValue(),
    ),
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
    if (periodType === 'custom' && (!customStart || !customEnd)) {
      setError('Please enter both start and end dates for custom range')
      return
    }
    mutation.mutate()
  }

  const periodLabel = periodType === 'month'
    ? (() => { const [y,m] = periodMonth.split('-'); return `${MONTHS[+m-1]} ${y}` })()
    : periodType === 'year' ? `Full year ${periodYear}`
    : periodType === 'custom' ? `${customStart} → ${customEnd}`
    : 'All dates (no filter)'

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

        {/* ── Period filter ── */}
        <div className="bg-blue-50 border border-blue-200 rounded-xl p-5 space-y-4">
          <div className="flex items-center gap-2 text-blue-800 font-semibold text-sm">
            <Calendar className="w-4 h-4" />
            Timesheet Period
            <span className="ml-auto text-xs font-normal text-blue-600 bg-blue-100 px-2 py-0.5 rounded-full">
              Default: current month
            </span>
          </div>

          {/* Type selector */}
          <div className="grid grid-cols-4 gap-2">
            {(['month', 'year', 'custom', 'all'] as const).map(t => (
              <button
                key={t}
                type="button"
                onClick={() => setPeriodType(t)}
                className={`py-2 px-3 rounded-lg text-xs font-medium border transition-colors ${
                  periodType === t
                    ? 'bg-blue-600 text-white border-blue-600'
                    : 'bg-white text-gray-600 border-gray-300 hover:border-blue-400'
                }`}
              >
                {t === 'all' ? 'All Dates' : t.charAt(0).toUpperCase() + t.slice(1)}
              </button>
            ))}
          </div>

          {/* Month picker */}
          {periodType === 'month' && (
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-xs text-blue-700 font-medium mb-1">Month</label>
                <select
                  value={periodMonth.split('-')[1]}
                  onChange={(e) => setPeriodMonth(`${periodMonth.split('-')[0]}-${e.target.value}`)}
                  className="w-full border border-blue-200 rounded-lg px-3 py-2 text-sm bg-white"
                >
                  {MONTHS.map((m, i) => (
                    <option key={m} value={String(i+1).padStart(2,'0')}>{m}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="block text-xs text-blue-700 font-medium mb-1">Year</label>
                <select
                  value={periodMonth.split('-')[0]}
                  onChange={(e) => setPeriodMonth(`${e.target.value}-${periodMonth.split('-')[1]}`)}
                  className="w-full border border-blue-200 rounded-lg px-3 py-2 text-sm bg-white"
                >
                  {years.map(y => <option key={y} value={y}>{y}</option>)}
                </select>
              </div>
            </div>
          )}

          {/* Year picker */}
          {periodType === 'year' && (
            <div>
              <label className="block text-xs text-blue-700 font-medium mb-1">Year</label>
              <select
                value={periodYear}
                onChange={(e) => setPeriodYear(e.target.value)}
                className="w-full border border-blue-200 rounded-lg px-3 py-2 text-sm bg-white"
              >
                {years.map(y => <option key={y} value={y}>{y}</option>)}
              </select>
            </div>
          )}

          {/* Custom range */}
          {periodType === 'custom' && (
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-xs text-blue-700 font-medium mb-1">From</label>
                <input type="date" value={customStart} onChange={(e) => setCustomStart(e.target.value)}
                  className="w-full border border-blue-200 rounded-lg px-3 py-2 text-sm bg-white" />
              </div>
              <div>
                <label className="block text-xs text-blue-700 font-medium mb-1">To</label>
                <input type="date" value={customEnd} onChange={(e) => setCustomEnd(e.target.value)}
                  className="w-full border border-blue-200 rounded-lg px-3 py-2 text-sm bg-white" />
              </div>
            </div>
          )}

          {periodType !== 'all' && (
            <div className="text-xs text-blue-700 bg-blue-100 rounded-lg px-3 py-2">
              Will process entries for: <strong>{periodLabel}</strong>
            </div>
          )}
        </div>

        {/* ── Drop zone ── */}
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
                <p className="text-sm">{isDragActive ? 'Drop it here' : 'Drag & drop a ZIP, or click to browse'}</p>
                <p className="text-xs">PDF, XLSX, DOCX, PNG, JPG, CSV — all supported · Max 2 GB</p>
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
            placeholder={`e.g. ${periodLabel} payroll batch`}
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
          <ProgressBar value={progress} label="Uploading…" color="blue" />
        )}

        {/* Submit */}
        <button
          type="submit"
          disabled={mutation.isPending || !file}
          className="w-full bg-blue-600 text-white font-medium py-3 rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center justify-center gap-2"
        >
          {mutation.isPending ? (
            <><span className="animate-spin inline-block w-4 h-4 border-2 border-white border-t-transparent rounded-full" /> Processing…</>
          ) : (
            <><Upload className="w-4 h-4" /> Upload &amp; Process</>
          )}
        </button>
      </form>
    </div>
  )
}
