'use client'
import { Fragment, useState, useCallback, useRef, useEffect } from 'react'
import axios from 'axios'
import {
  Upload, ChevronRight, CheckCircle2, XCircle, Loader2,
  FileText, Search, Brain, Zap, Camera, BarChart3, Copy,
  Check, Clock, ArrowRight, RotateCcw, FlaskConical,
  Layers, AlertTriangle, Play, Send, Download, Cpu, Trophy,
  ChevronDown, ChevronUp,
} from 'lucide-react'
import MonthCalendar, { DayEntry } from '@/components/MonthCalendar'

const API = '/api/v1/debug/lab'

// Map the V2 daily records into the calendar's day-entry shape.
function v2ToDayEntries(records: V2DailyRecord[]): DayEntry[] {
  return (records || []).filter(r => r.date).map(r => {
    let entry_type = 'WORK', leave_type: string | null = null
    if ((r.holiday_hours || 0) > 0) entry_type = 'HOLIDAY'
    else if ((r.sick_hours || 0) > 0) { entry_type = 'LEAVE'; leave_type = 'Sick' }
    else if ((r.vacation_hours || 0) > 0) { entry_type = 'LEAVE'; leave_type = 'Vacation' }
    else if (!r.worked || (r.total_hours || 0) === 0) entry_type = 'WEEKEND'
    return {
      date: r.date, hours: r.total_hours || 0,
      regular_hours: r.regular_hours, overtime_hours: r.overtime_hours,
      entry_type, leave_type,
      in_time: r.in_time, out_time: r.out_time,
      break_minutes: r.lunch_hours ? Math.round(r.lunch_hours * 60) : 0,
    }
  })
}

// ── Types ──────────────────────────────────────────────────────────────────────
interface ParserDef { id: string; name: string; desc: string; category: string }
interface UploadResult {
  session_id: string
  file_info: { filename: string; ext: string; size_kb: number; is_pdf: boolean; is_image: boolean }
  pdf_classification?: any
  available_parsers: ParserDef[]
}
interface ParserResult {
  parser: string; status: 'success'|'error'; duration_ms: number
  text: string; text_chars: number; tables: number; error?: string
  vlm_entries?: any[]; page_results?: Array<{page: number; status: string; chars?: number; lines?: number; duration_ms?: number; preview?: string; error?: string; ocr_engine?: string; ocr_chars?: number; ocr_confidence?: number; fused_chars?: number}>
  pages_processed?: number; model?: string; errors?: string[]; vlm_summary?: string
  ocr_text?: string; fusion_summary?: string; warnings?: string[]
}
interface LLMResult {
  status: 'success'|'error'|'skipped'|'warning'; duration_ms: number
  provider: string; model: string; employee_name?: string
  entries: any[]; summary: any; prompt_preview: string; error?: string
  v2_result?: V2Result
}
interface V2DailyRecord {
  date: string; day: string | null; worked: boolean
  in_time: string | null; out_time: string | null; lunch_hours: number
  regular_hours: number; sick_hours: number; vacation_hours: number
  holiday_hours: number; overtime_hours: number; total_hours: number
  evidence: string | null
}
interface V2Result {
  target_month: string
  employee_name: string | null
  employer_name: { value: string | null; confidence: number; evidence: string | null }
  period: { start_date: string | null; end_date: string | null; source_text: string | null }
  daily_records: V2DailyRecord[]
  summary: {
    worked_days_count: number; total_regular_hours: number; total_sick_hours: number
    total_vacation_hours: number; total_holiday_hours: number
    total_overtime_hours: number; total_payable_hours: number
    document_reported_total_hours: number | null
  }
  overtime: {
    has_overtime: boolean; daily_overtime_hours: number
    weekly_overtime_hours: number; total_overtime_hours: number; policy_used: string
  }
  manager_approval: {
    status: 'approved'|'not_found'|'unclear'
    manager_name: string | null; approval_date: string | null; evidence: string | null
  }
  ignored_dates: Array<{ date: string; reason: string }>
  validation: {
    validation_status: 'matched'|'mismatch'|'missing_document_total'|'unclear'
    calculated_total: number; document_total: number | null; issues: string[]
  }
}
interface ModelDef {
  id: string; name: string; description: string; role: string
  size_gb: number; design_doc: string | null; pulled: boolean; default: boolean
}
interface BenchResult {
  model_id: string; status: string; duration_ms: number
  employee_name?: string; entries: any[]; summary: any
  error?: string; raw_response_chars?: number
  _score?: number; _recommended?: boolean; v2_result?: V2Result
}
interface BenchmarkResult {
  session_id: string; parser_used: string; models_run: number
  results: BenchResult[]; best_model: string | null; duration_ms: number
}
// Live per-model state during a benchmark run. Was referenced in 8 places but
// never declared — broke `next build` under strict mode.
interface ModelRunStatus {
  state: 'pending' | 'running' | 'done' | 'error'
  result?: BenchResult
  error?: string
}

const ROLE_COLORS: Record<string, string> = {
  primary:      'bg-indigo-100 text-indigo-700',
  fast_helper:  'bg-blue-100 text-blue-700',
  review:       'bg-purple-100 text-purple-700',
  fast:         'bg-green-100 text-green-700',
  fallback:     'bg-gray-100 text-gray-600',
}

const CATEGORY_COLORS: Record<string, string> = {
  text: 'border-blue-200 bg-blue-50',
  ai:   'border-indigo-200 bg-indigo-50',
  ocr:  'border-purple-200 bg-purple-50',
  vlm:  'border-pink-200 bg-pink-50',
}
const CATEGORY_ICONS: Record<string, React.ReactNode> = {
  text: <FileText className="w-3.5 h-3.5" />,
  ai:   <Brain className="w-3.5 h-3.5" />,
  ocr:  <Search className="w-3.5 h-3.5" />,
  vlm:  <Camera className="w-3.5 h-3.5" />,
}

// ── Main ───────────────────────────────────────────────────────────────────────

export default function TestLabPage() {
  const [step, setStep] = useState<1|2|3>(1)

  // Period filter — set before upload, used in every LLM call
  const now = new Date()
  const [periodMonth, setPeriodMonth] = useState<number>(now.getMonth() + 1) // 1-12
  const [periodYear,  setPeriodYear]  = useState<number>(now.getFullYear())

  // Step 1
  const [uploadResult, setUploadResult] = useState<UploadResult | null>(null)
  const [uploading, setUploading]       = useState(false)
  const [dragging, setDragging]         = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)

  // Step 2
  const [parserResults, setParserResults]   = useState<Record<string, ParserResult>>({})
  const [runningParser, setRunningParser]   = useState<string | null>(null)
  const [selectedParser, setSelectedParser] = useState<string | null>(null)
  const [viewingParser, setViewingParser]   = useState<string | null>(null)

  // Step 3 — single model
  const [llmResult, setLLMResult]   = useState<LLMResult | null>(null)
  const [runningLLM, setRunningLLM] = useState(false)
  const [llmProgress, setLlmProgress] = useState<string>('')

  // Step 3 — model management + benchmark
  const [models, setModels]                 = useState<ModelDef[]>([])
  const [selectedModels, setSelectedModels] = useState<Set<string>>(new Set(['qwen3:14b']))
  const [pullingModel, setPullingModel]     = useState<string | null>(null)
  const [pullProgress, setPullProgress]     = useState<Record<string, string>>({})
  const [warmingModel, setWarmingModel]     = useState<string | null>(null)
  const [benchResult, setBenchResult]       = useState<BenchmarkResult | null>(null)
  const [runningBench, setRunningBench]     = useState(false)
  const [benchMode, setBenchMode]           = useState(false)   // toggle single vs bench
  // Live per-model status during a benchmark run
  const [modelRunStatus, setModelRunStatus] = useState<Record<string, ModelRunStatus>>({})

  // Aborts the in-flight streaming fetch (run-llm / benchmark) on reset/unmount
  // so we don't leak the reader or setState on an unmounted component.
  const abortRef = useRef<AbortController | null>(null)

  const reset = () => {
    abortRef.current?.abort()
    setStep(1); setUploadResult(null); setParserResults({})
    setRunningParser(null); setSelectedParser(null); setViewingParser(null)
    setLLMResult(null); setRunningLLM(false); setLlmProgress('')
    setBenchResult(null); setRunningBench(false); setModelRunStatus({})
  }

  // Abort any in-flight stream when the component unmounts.
  useEffect(() => () => abortRef.current?.abort(), [])

  // Load model catalog on mount
  useEffect(() => {
    axios.get<{ models: ModelDef[] }>(`${API}/models`)
      .then(r => setModels(r.data.models))
      .catch(() => {})
  }, [])

  const refreshModels = () => {
    axios.get<{ models: ModelDef[] }>(`${API}/models`)
      .then(r => setModels(r.data.models))
      .catch(() => {})
  }

  // ── Upload ─────────────────────────────────────────────────────────────────
  const upload = async (f: File) => {
    setUploading(true)
    try {
      const fd = new FormData(); fd.append('file', f)
      const { data } = await axios.post<UploadResult>(`${API}/upload`, fd, { timeout: 60000 })
      setUploadResult(data)
      setStep(2)
    } catch (e: any) {
      alert(e.response?.data?.detail || e.message)
    } finally { setUploading(false) }
  }

  const onDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault(); setDragging(false)
    const f = e.dataTransfer.files[0]; if (f) upload(f)
  }, [])

  // ── Run parser ─────────────────────────────────────────────────────────────
  const runParser = async (parserId: string) => {
    if (!uploadResult || runningParser) return
    setRunningParser(parserId)
    try {
      const { data } = await axios.post<ParserResult>(
        `${API}/${uploadResult.session_id}/run-parser`,
        { parser: parserId }, {
          timeout: 360000,
          transformResponse: [(raw: string) => {
            if (!raw) return raw
            const trimmed = raw.trim()
            const lastBrace = trimmed.lastIndexOf('{')
            if (lastBrace === -1) {
              try { return JSON.parse(trimmed) } catch { return raw }
            }
            try { return JSON.parse(trimmed.slice(lastBrace)) } catch {
              try { return JSON.parse(trimmed) } catch { return raw }
            }
          }],
        }
      )
      setParserResults(prev => ({ ...prev, [parserId]: data }))
    } catch (e: any) {
      setParserResults(prev => ({
        ...prev, [parserId]: { parser: parserId, status: 'error', duration_ms: 0,
          text: '', text_chars: 0, tables: 0, error: e.response?.data?.detail || e.message }
      }))
    } finally { setRunningParser(null) }
  }

  // ── Run LLM (single model) ──────────────────────────────────────────────────
  const _llmInFlight = useRef(false)
  const runLLM = async () => {
    if (!uploadResult || !selectedParser) return
    if (_llmInFlight.current) return
    const pr = parserResults[selectedParser]
    if (!pr || !pr.text) return
    _llmInFlight.current = true
    abortRef.current?.abort()
    abortRef.current = new AbortController()
    setRunningLLM(true); setStep(3); setLLMResult(null); setBenchResult(null)
    setLlmProgress('Starting extraction…')
    try {
      const resp = await fetch(
        `${API}/${uploadResult.session_id}/run-llm`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            text: pr.text,
            parser_used: selectedParser,
            period_filter: { month: periodMonth, year: periodYear },
          }),
          signal: abortRef.current.signal,
          // no timeout — LLM can take many minutes for large docs
        }
      )
      if (!resp.ok || !resp.body) {
        throw new Error(`HTTP ${resp.status}: ${await resp.text()}`)
      }
      const reader = resp.body.getReader()
      const dec    = new TextDecoder()
      let   buf    = ''
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buf += dec.decode(value, { stream: true })
        const lines = buf.split('\n')
        buf = lines.pop() ?? ''   // keep incomplete last line in buffer
        for (const line of lines) {
          const trimmed = line.trim()
          if (!trimmed) continue
          try {
            const obj = JSON.parse(trimmed)
            if (obj.type === 'progress') {
              setLlmProgress(obj.message || `Processing… ${Math.round((obj.elapsed_ms ?? 0) / 1000)}s`)
            } else if (obj.type === 'start') {
              setLlmProgress(obj.message || 'Starting…')
            } else if (obj.type === 'result') {
              // Strip the "type" wrapper and set as the LLM result
              const { type: _t, ...result } = obj
              setLLMResult(result as LLMResult)
              setLlmProgress('')
            }
          } catch { /* non-JSON line */ }
        }
      }
    } catch (e: any) {
      if (e?.name !== 'AbortError') {
        setLLMResult({ status: 'error', duration_ms: 0, provider: '', model: '',
          entries: [], summary: {}, prompt_preview: '',
          error: e.message })
      }
      setLlmProgress('')
    } finally { setRunningLLM(false); _llmInFlight.current = false }
  }

  // ── Pull a model ────────────────────────────────────────────────────────────
  const pullModel = async (modelId: string) => {
    setPullingModel(modelId)
    setPullProgress(p => ({ ...p, [modelId]: 'Starting pull…' }))
    try {
      const resp = await fetch(`${API}/models/${encodeURIComponent(modelId)}/pull`, { method: 'POST' })
      const reader = resp.body?.getReader()
      if (!reader) return
      const dec = new TextDecoder()
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        const lines = dec.decode(value).split('\n').filter(Boolean)
        for (const line of lines) {
          try {
            const obj = JSON.parse(line)
            const msg = obj.status || obj.error || ''
            const pct = obj.completed && obj.total
              ? ` ${Math.round(obj.completed / obj.total * 100)}%` : ''
            if (msg) setPullProgress(p => ({ ...p, [modelId]: msg + pct }))
          } catch { /* ndjson line */ }
        }
      }
    } catch (e: any) {
      setPullProgress(p => ({ ...p, [modelId]: `Error: ${e.message}` }))
    } finally {
      setPullingModel(null)
      refreshModels()
    }
  }

  // ── Warm up a model ─────────────────────────────────────────────────────────
  const warmupModel = async (modelId: string) => {
    setWarmingModel(modelId)
    try {
      await axios.post(`${API}/models/${encodeURIComponent(modelId)}/warmup`, {}, {
        timeout: 300000,
        transformResponse: (raw: string) => {
          const lines = raw.split('\n').filter(Boolean)
          for (let i = lines.length - 1; i >= 0; i--) {
            try { return JSON.parse(lines[i]) } catch { /* skip */ }
          }
          return {}
        },
      })
    } catch { /* ignore */ }
    finally { setWarmingModel(null) }
  }

  // ── Run Benchmark ───────────────────────────────────────────────────────────
  const _benchInFlight = useRef(false)
  const runBenchmark = async () => {
    if (!uploadResult || !selectedParser) return
    if (_benchInFlight.current) return
    const pr = parserResults[selectedParser]
    if (!pr || !pr.text) return
    if (selectedModels.size === 0) { alert('Select at least one model'); return }

    _benchInFlight.current = true
    abortRef.current?.abort()
    abortRef.current = new AbortController()
    setRunningBench(true)
    setStep(3)
    setBenchResult(null)
    setLLMResult(null)

    // Initialise all selected models as "pending"
    const initStatus: Record<string, ModelRunStatus> = {}
    for (const mid of selectedModels) initStatus[mid] = { state: 'pending' }
    setModelRunStatus(initStatus)

    try {
      const resp = await fetch(
        `${API}/${uploadResult.session_id}/run-llm-bench`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            text: pr.text,
            parser_used: selectedParser,
            models: Array.from(selectedModels),
            period_filter: { month: periodMonth, year: periodYear },
          }),
          signal: abortRef.current.signal,
        }
      )

      if (!resp.ok) {
        const err = await resp.text()
        alert(`Benchmark request failed (${resp.status}): ${err.slice(0, 200)}`)
        return
      }

      const reader = resp.body?.getReader()
      if (!reader) { alert('No response body'); return }

      const dec = new TextDecoder()
      let buf = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buf += dec.decode(value, { stream: true })

        // Process all complete NDJSON lines buffered so far
        const lines = buf.split('\n')
        buf = lines.pop() ?? ''   // last item is the incomplete line

        for (const line of lines) {
          const trimmed = line.trim()
          if (!trimmed) continue
          try {
            const msg = JSON.parse(trimmed)

            if (msg.type === 'start') {
              // re-init in case models list came from server
              const s: Record<string, ModelRunStatus> = {}
              for (const mid of (msg.models as string[])) s[mid] = { state: 'pending' }
              setModelRunStatus(s)

            } else if (msg.type === 'running') {
              const mid: string = msg.model
              setModelRunStatus(prev => ({ ...prev, [mid]: { state: 'running' } }))

            } else if (msg.type === 'result') {
              const mid: string = msg.model
              const r: BenchResult = msg.result
              setModelRunStatus(prev => ({
                ...prev,
                [mid]: {
                  state: r.status === 'success' ? 'done' : 'error',
                  result: r,
                  error: r.error,
                },
              }))

            } else if (msg.type === 'complete') {
              // Full benchmark finished — set final result
              const final: BenchmarkResult = {
                session_id:  msg.session_id,
                parser_used: msg.parser_used,
                models_run:  msg.models_run,
                results:     msg.results,
                best_model:  msg.best_model,
                duration_ms: msg.duration_ms,
              }
              setBenchResult(final)
            }
          } catch { /* malformed line — skip */ }
        }
      }

      // Handle any remaining buffered data
      if (buf.trim()) {
        try {
          const msg = JSON.parse(buf.trim())
          if (msg.type === 'complete') {
            setBenchResult({
              session_id: msg.session_id, parser_used: msg.parser_used,
              models_run: msg.models_run, results: msg.results,
              best_model: msg.best_model, duration_ms: msg.duration_ms,
            })
          }
        } catch { /* ignore */ }
      }

    } catch (e: any) {
      if (e?.name !== 'AbortError') alert('Benchmark failed: ' + e.message)
    } finally {
      setRunningBench(false)
      _benchInFlight.current = false
    }
  }

  const fi = uploadResult?.file_info
  const parsers = uploadResult?.available_parsers || []
  const selectedResult = selectedParser ? parserResults[selectedParser] : null

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <div className="bg-white border-b px-8 py-4">
        <div className="max-w-5xl mx-auto flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-blue-600 to-indigo-700 flex items-center justify-center">
              <FlaskConical className="w-5 h-5 text-white" />
            </div>
            <div>
              <h1 className="text-lg font-bold text-gray-900">Pipeline Test Lab</h1>
              <p className="text-xs text-gray-400">Upload → Parse → Extract</p>
            </div>
          </div>
          {uploadResult && (
            <button onClick={reset} className="flex items-center gap-1.5 text-xs text-gray-500 hover:text-gray-800 bg-gray-100 hover:bg-gray-200 px-3 py-1.5 rounded-lg transition-colors">
              <RotateCcw className="w-3 h-3" /> Start over
            </button>
          )}
        </div>
      </div>

      {/* Step indicator */}
      <div className="bg-white border-b">
        <div className="max-w-5xl mx-auto px-8 py-3 flex items-center gap-2">
          {([
            { n: 1, label: 'Upload' },
            { n: 2, label: 'Select Parser' },
            { n: 3, label: 'LLM Extract' },
          ] as const).map(({ n, label }, i) => (
            <Fragment key={n}>
              <button
                onClick={() => { if (n <= step || (n === 2 && uploadResult)) setStep(n) }}
                className={`flex items-center gap-2 px-4 py-1.5 rounded-full text-sm font-medium transition-colors ${
                  step === n
                    ? 'bg-blue-600 text-white'
                    : n < step
                    ? 'bg-green-100 text-green-700 hover:bg-green-200'
                    : 'bg-gray-100 text-gray-400'
                }`}>
                <span className={`w-5 h-5 rounded-full flex items-center justify-center text-xs font-bold ${
                  step === n ? 'bg-white/30 text-white' : n < step ? 'bg-green-500 text-white' : 'bg-gray-300 text-gray-500'
                }`}>{n < step ? '✓' : n}</span>
                {label}
              </button>
              {i < 2 && <ChevronRight className="w-4 h-4 text-gray-300 flex-shrink-0" />}
            </Fragment>
          ))}
          {uploadResult && (
            <div className="ml-auto flex items-center gap-1.5 text-xs text-gray-500 bg-gray-50 border border-gray-200 px-3 py-1 rounded-lg">
              <FileText className="w-3 h-3" />
              {fi?.filename} · {fi?.size_kb} KB
            </div>
          )}
        </div>
      </div>

      <div className="max-w-5xl mx-auto px-8 py-6">

        {/* ── STEP 1: Upload ────────────────────────────────────────────────── */}
        {step === 1 && (
          <div className="max-w-2xl mx-auto space-y-5">
            {/* Period picker */}
            <PeriodPicker
              month={periodMonth} year={periodYear}
              onChange={(m, y) => { setPeriodMonth(m); setPeriodYear(y) }}
            />

            <div>
              <h2 className="text-xl font-bold text-gray-800 mb-1">Upload a file</h2>
              <p className="text-sm text-gray-500 mb-4">Supports PDF, Excel, CSV, Word, PNG, JPG, TIFF</p>
              <div
                onDragOver={e => { e.preventDefault(); setDragging(true) }}
                onDragLeave={() => setDragging(false)}
                onDrop={onDrop}
                onClick={() => fileRef.current?.click()}
                className={`border-2 border-dashed rounded-2xl p-16 text-center cursor-pointer transition-all ${
                  dragging ? 'border-blue-400 bg-blue-50 scale-[1.01]'
                  : 'border-gray-300 bg-white hover:border-blue-400 hover:bg-blue-50/30'
                }`}>
                <input ref={fileRef} type="file" className="hidden"
                  accept=".pdf,.xlsx,.xls,.csv,.docx,.doc,.png,.jpg,.jpeg,.tiff,.webp"
                  onChange={e => { const f = e.target.files?.[0]; if (f) upload(f) }} />
                {uploading
                  ? <><Loader2 className="w-10 h-10 text-blue-500 mx-auto mb-3 animate-spin" /><p className="text-sm font-medium text-blue-600">Uploading and analysing…</p></>
                  : <><Upload className="w-10 h-10 text-gray-400 mx-auto mb-3" /><p className="text-base font-semibold text-gray-600">Drop your file here</p><p className="text-sm text-gray-400 mt-1">or click to browse</p></>}
              </div>
            </div>
          </div>
        )}

        {/* ── STEP 2: Parsers ──────────────────────────────────────────────── */}
        {step === 2 && uploadResult && (
          <div className="space-y-5">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-xl font-bold text-gray-800">Select a parser</h2>
                <p className="text-sm text-gray-500">Click any parser to run it · select the best result · send to LLM</p>
              </div>
              <div className="flex items-center gap-3">
                <PeriodBadge month={periodMonth} year={periodYear} onEdit={() => setStep(1)} />
                {selectedResult?.status === 'success' && (
                  <button onClick={runLLM}
                    className="flex items-center gap-2 bg-indigo-600 text-white px-5 py-2.5 rounded-xl font-semibold hover:bg-indigo-700 transition-colors shadow-sm">
                    <Send className="w-4 h-4" /> Send to LLM
                    <span className="text-indigo-200 text-xs">({selectedParser})</span>
                  </button>
                )}
              </div>
            </div>

            {/* PDF classification badge */}
            {uploadResult.pdf_classification && (
              <PdfTypeBadge data={uploadResult.pdf_classification} />
            )}

            {/* Parser grid */}
            {['text','ai','ocr','vlm'].map(cat => {
              const catParsers = parsers.filter(p => p.category === cat)
              if (!catParsers.length) return null
              const labels: Record<string, string> = {
                text: 'Text Parsers',
                ai:   'AI / Layout Parsers',
                ocr:  'OCR Engines',
                vlm:  'Vision LLM',
              }
              return (
                <div key={cat}>
                  <p className="text-xs font-bold text-gray-400 uppercase tracking-widest mb-2">{labels[cat]}</p>
                  <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                    {catParsers.map(p => (
                      <ParserCard key={p.id} parser={p}
                        result={parserResults[p.id]}
                        running={runningParser === p.id}
                        selected={selectedParser === p.id}
                        viewing={viewingParser === p.id}
                        onRun={() => runParser(p.id)}
                        onSelect={() => setSelectedParser(p.id)}
                        onView={() => setViewingParser(viewingParser === p.id ? null : p.id)}
                        disabled={!!runningParser && runningParser !== p.id}
                      />
                    ))}
                  </div>
                </div>
              )
            })}

            {/* Text viewer panel */}
            {viewingParser && parserResults[viewingParser]?.status === 'success' && (
              <div className="bg-gray-900 rounded-2xl overflow-hidden">
                <div className="flex items-center justify-between px-4 py-3 border-b border-gray-700">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-semibold text-white">{viewingParser}</span>
                    <span className="text-xs text-gray-400">
                      {parserResults[viewingParser].text_chars.toLocaleString()} chars
                      {parserResults[viewingParser].tables > 0 && ` · ${parserResults[viewingParser].tables} tables`}
                    </span>
                  </div>
                  <div className="flex gap-2">
                    <CopyButton text={parserResults[viewingParser].text} />
                    {selectedParser !== viewingParser && (
                      <button onClick={() => setSelectedParser(viewingParser)}
                        className="text-xs bg-indigo-500 text-white px-3 py-1 rounded-lg hover:bg-indigo-400 transition-colors">
                        Select this
                      </button>
                    )}
                  </div>
                </div>
                <pre className="text-xs text-gray-200 font-mono overflow-auto max-h-72 p-4 whitespace-pre-wrap leading-relaxed">
                  {parserResults[viewingParser].text || '(no text extracted)'}
                </pre>
              </div>
            )}

            {/* OCR + VLM fusion diagnostic: raw OCR transcript ↔ fused Markdown */}
            {viewingParser && parserResults[viewingParser]?.status === 'success'
              && parserResults[viewingParser].ocr_text !== undefined && (
              <FusionDiagnostic result={parserResults[viewingParser]} />
            )}

            {/* Bottom send button */}
            {selectedResult?.status === 'success' && (
              <div className="flex justify-end pt-2">
                <button onClick={runLLM}
                  className="flex items-center gap-2 bg-indigo-600 text-white px-6 py-3 rounded-xl font-semibold hover:bg-indigo-700 transition-colors shadow">
                  <Send className="w-4 h-4" />
                  Send "{selectedParser}" output to LLM →
                </button>
              </div>
            )}
          </div>
        )}

        {/* ── STEP 3: LLM ──────────────────────────────────────────────────── */}
        {step === 3 && (
          <div className="space-y-5">
            <div className="flex items-center justify-between flex-wrap gap-3">
              <div>
                <h2 className="text-xl font-bold text-gray-800">LLM Extraction</h2>
                <p className="text-sm text-gray-500">
                  Feeding <span className="font-semibold text-indigo-600">{selectedParser}</span> output into the LLM
                </p>
              </div>
              <div className="flex items-center gap-2">
                <PeriodBadge month={periodMonth} year={periodYear} onEdit={() => setStep(1)} />
                {/* Single / Benchmark toggle */}
                <div className="flex bg-gray-100 rounded-lg p-1 gap-1">
                  <button onClick={() => setBenchMode(false)}
                    className={`px-3 py-1.5 text-xs font-semibold rounded-md transition-colors ${!benchMode ? 'bg-white text-indigo-700 shadow-sm' : 'text-gray-500'}`}>
                    Single
                  </button>
                  <button onClick={() => setBenchMode(true)}
                    className={`px-3 py-1.5 text-xs font-semibold rounded-md transition-colors ${benchMode ? 'bg-white text-indigo-700 shadow-sm' : 'text-gray-500'}`}>
                    Benchmark
                  </button>
                </div>
                <button onClick={() => setStep(2)}
                  className="text-xs text-gray-500 hover:text-gray-800 bg-gray-100 hover:bg-gray-200 px-3 py-1.5 rounded-lg transition-colors">
                  ← Back
                </button>
              </div>
            </div>

            {/* ── Model Manager ──────────────────────────────────────────────── */}
            <ModelManager
              models={models}
              selectedModels={selectedModels}
              onToggleModel={(id) => setSelectedModels(prev => {
                const n = new Set(prev)
                if (n.has(id)) n.delete(id); else n.add(id)
                return n
              })}
              pullingModel={pullingModel}
              pullProgress={pullProgress}
              warmingModel={warmingModel}
              onPull={pullModel}
              onWarmup={warmupModel}
              benchMode={benchMode}
              modelRunStatus={modelRunStatus}
            />

            {/* ── Single Model Run ────────────────────────────────────────────── */}
            {!benchMode && (
              <div className="space-y-4">
                <button onClick={runLLM} disabled={runningLLM || !selectedParser}
                  className="w-full flex items-center justify-center gap-2 bg-indigo-600 hover:bg-indigo-700 disabled:bg-indigo-300 text-white font-semibold py-3 rounded-xl transition-colors">
                  {runningLLM ? <><Loader2 className="w-4 h-4 animate-spin" /> Extracting…</> : <><Send className="w-4 h-4" /> Run LLM Extraction</>}
                </button>
                {runningLLM && (
                  <div className="bg-white border border-indigo-200 rounded-2xl p-8 text-center">
                    <Loader2 className="w-10 h-10 text-indigo-500 mx-auto mb-3 animate-spin" />
                    <p className="text-sm font-medium text-indigo-700">
                      {llmProgress || 'LLM is extracting timesheet data…'}
                    </p>
                    <p className="text-xs text-gray-400 mt-1">
                      qwen3:14b — large documents may take several minutes
                    </p>
                  </div>
                )}
                {llmResult && !runningLLM && (
                  <LLMResultView result={llmResult} parserUsed={selectedParser || ''} />
                )}
              </div>
            )}

            {/* ── Benchmark Mode ──────────────────────────────────────────────── */}
            {benchMode && (
              <div className="space-y-4">
                <div className="bg-blue-50 border border-blue-200 rounded-xl p-4 text-sm text-blue-800">
                  <p className="font-semibold mb-1">Benchmark mode</p>
                  <p className="text-xs">Each selected model runs extraction on the same parsed text. Results are compared side by side. Models run <strong>sequentially</strong> to avoid GPU memory pressure.</p>
                  <p className="text-xs mt-1">Estimated time: ~{Math.ceil(selectedModels.size * 1.5)} min for {selectedModels.size} model{selectedModels.size !== 1 ? 's' : ''}</p>
                </div>
                <button onClick={runBenchmark} disabled={runningBench || selectedModels.size === 0}
                  className="w-full flex items-center justify-center gap-2 bg-purple-600 hover:bg-purple-700 disabled:bg-purple-300 text-white font-semibold py-3 rounded-xl transition-colors">
                  {runningBench
                    ? <><Loader2 className="w-4 h-4 animate-spin" /> Running {selectedModels.size} models sequentially…</>
                    : <><BarChart3 className="w-4 h-4" /> Run Benchmark ({selectedModels.size} model{selectedModels.size !== 1 ? 's' : ''})</>}
                </button>
                {runningBench && (
                  <div className="bg-white border border-purple-200 rounded-2xl p-5 space-y-2">
                    <div className="flex items-center gap-2 mb-3">
                      <Loader2 className="w-4 h-4 text-purple-500 animate-spin" />
                      <p className="text-sm font-semibold text-purple-700">Benchmark running…</p>
                      <span className="text-xs text-gray-400">results appear as each model finishes</span>
                    </div>
                    {Array.from(selectedModels).map(mid => {
                      const s = modelRunStatus[mid]
                      return (
                        <div key={mid} className={`flex items-center gap-3 px-4 py-2.5 rounded-xl border text-sm transition-colors ${
                          s?.state === 'running' ? 'bg-blue-50 border-blue-300'
                          : s?.state === 'done'    ? 'bg-green-50 border-green-300'
                          : s?.state === 'error'   ? 'bg-red-50 border-red-300'
                          : 'bg-gray-50 border-gray-200'
                        }`}>
                          {s?.state === 'running' ? <Loader2 className="w-4 h-4 text-blue-500 animate-spin shrink-0" />
                          : s?.state === 'done'    ? <CheckCircle2 className="w-4 h-4 text-green-500 shrink-0" />
                          : s?.state === 'error'   ? <XCircle className="w-4 h-4 text-red-500 shrink-0" />
                          : <Clock className="w-4 h-4 text-gray-300 shrink-0" />}
                          <span className={`font-semibold flex-1 ${
                            s?.state === 'running' ? 'text-blue-700'
                            : s?.state === 'done'  ? 'text-green-700'
                            : s?.state === 'error' ? 'text-red-700'
                            : 'text-gray-400'
                          }`}>{mid}</span>
                          {s?.state === 'running' && <span className="text-xs text-blue-500 animate-pulse">processing…</span>}
                          {s?.state === 'done' && s.result && (
                            <span className="text-xs text-green-600 font-mono">
                              {s.result.summary?.entries_found ?? 0} entries · {s.result.summary?.total_hours ?? 0}h · {(s.result.duration_ms/1000).toFixed(1)}s
                            </span>
                          )}
                          {s?.state === 'error' && (
                            <span className="text-xs text-red-500 truncate max-w-48">{s.error || 'failed'}</span>
                          )}
                        </div>
                      )
                    })}
                  </div>
                )}
                {benchResult && !runningBench && (
                  <BenchmarkView result={benchResult} />
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

// ── Period Picker ──────────────────────────────────────────────────────────────

const MONTH_NAMES = [
  'January','February','March','April','May','June',
  'July','August','September','October','November','December',
]

function PeriodPicker({ month, year, onChange }: {
  month: number; year: number
  onChange: (month: number, year: number) => void
}) {
  // Build a reasonable year range: 3 years back → 1 year forward
  const thisYear = new Date().getFullYear()
  const years = Array.from({ length: 5 }, (_, i) => thisYear - 3 + i)

  return (
    <div className="bg-gradient-to-r from-indigo-50 to-blue-50 border border-indigo-200 rounded-2xl p-5">
      <div className="flex items-center gap-2 mb-3">
        <div className="w-7 h-7 rounded-lg bg-indigo-600 flex items-center justify-center">
          <span className="text-white text-xs font-bold">📅</span>
        </div>
        <div>
          <p className="text-sm font-bold text-indigo-800">Timesheet Period</p>
          <p className="text-xs text-indigo-500">LLM will only extract entries within this month. Dates outside are ignored.</p>
        </div>
      </div>
      <div className="flex items-center gap-3">
        <select
          value={month}
          onChange={e => onChange(Number(e.target.value), year)}
          className="flex-1 px-3 py-2.5 rounded-xl border border-indigo-300 bg-white text-sm font-semibold text-gray-800 focus:outline-none focus:ring-2 focus:ring-indigo-400 cursor-pointer"
        >
          {MONTH_NAMES.map((name, i) => (
            <option key={i+1} value={i+1}>{name}</option>
          ))}
        </select>
        <select
          value={year}
          onChange={e => onChange(month, Number(e.target.value))}
          className="w-28 px-3 py-2.5 rounded-xl border border-indigo-300 bg-white text-sm font-semibold text-gray-800 focus:outline-none focus:ring-2 focus:ring-indigo-400 cursor-pointer"
        >
          {years.map(y => <option key={y} value={y}>{y}</option>)}
        </select>
        <div className="bg-indigo-600 text-white px-4 py-2.5 rounded-xl text-sm font-bold whitespace-nowrap">
          {MONTH_NAMES[month - 1]} {year}
        </div>
      </div>
    </div>
  )
}

function PeriodBadge({ month, year, onEdit }: { month: number; year: number; onEdit: () => void }) {
  return (
    <button onClick={onEdit}
      className="flex items-center gap-1.5 bg-indigo-100 hover:bg-indigo-200 text-indigo-700 px-3 py-1.5 rounded-lg text-xs font-semibold transition-colors">
      📅 {MONTH_NAMES[month - 1]} {year}
      <span className="text-indigo-400 text-[10px]">✎</span>
    </button>
  )
}

// ── OCR + VLM fusion diagnostic ─────────────────────────────────────────────────

function FusionDiagnostic({ result }: { result: ParserResult }) {
  const pages = (result.page_results || []).filter(p => p.ocr_engine || p.ocr_chars !== undefined)
  return (
    <div className="bg-white border border-indigo-200 rounded-2xl overflow-hidden">
      <div className="px-4 py-3 border-b border-indigo-100 bg-indigo-50">
        <div className="text-sm font-semibold text-indigo-900">OCR + VLM fusion — correlation</div>
        <div className="text-xs text-indigo-700 mt-0.5">
          OCR extracts accurate characters; the VLM rebuilds table layout grounded on that text.
          {result.model && <> · model <span className="font-mono">{result.model}</span></>}
        </div>
      </div>

      {pages.length > 0 && (
        <div className="px-4 py-3 border-b border-gray-100 overflow-x-auto">
          <table className="w-full text-xs text-gray-600">
            <thead>
              <tr className="text-left text-gray-400">
                <th className="pr-4 font-medium">Page</th>
                <th className="pr-4 font-medium">OCR engine</th>
                <th className="pr-4 font-medium">OCR chars</th>
                <th className="pr-4 font-medium">OCR conf</th>
                <th className="pr-4 font-medium">Fused chars</th>
                <th className="pr-4 font-medium">ms</th>
              </tr>
            </thead>
            <tbody>
              {pages.map((pg) => (
                <tr key={pg.page} className="border-t border-gray-50">
                  <td className="pr-4 py-1">{pg.page}</td>
                  <td className="pr-4 py-1 font-mono">{pg.ocr_engine ?? '—'}</td>
                  <td className="pr-4 py-1">{pg.ocr_chars?.toLocaleString() ?? '—'}</td>
                  <td className="pr-4 py-1">{pg.ocr_confidence != null ? pg.ocr_confidence.toFixed(2) : '—'}</td>
                  <td className="pr-4 py-1">{pg.fused_chars?.toLocaleString() ?? '—'}</td>
                  <td className="pr-4 py-1">{pg.duration_ms ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 divide-y md:divide-y-0 md:divide-x divide-gray-100">
        <div>
          <div className="flex items-center justify-between px-4 py-2 bg-gray-50 border-b border-gray-100">
            <span className="text-xs font-semibold text-gray-700">1 · Raw OCR transcript</span>
            <CopyButton text={result.ocr_text || ''} />
          </div>
          <pre className="text-[11px] text-gray-700 font-mono overflow-auto max-h-80 p-3 whitespace-pre-wrap leading-relaxed">
            {result.ocr_text || '(no OCR text)'}
          </pre>
        </div>
        <div>
          <div className="flex items-center justify-between px-4 py-2 bg-emerald-50 border-b border-emerald-100">
            <span className="text-xs font-semibold text-emerald-800">2 · Fused Markdown (structured)</span>
            <CopyButton text={result.text || ''} />
          </div>
          <pre className="text-[11px] text-gray-800 font-mono overflow-auto max-h-80 p-3 whitespace-pre-wrap leading-relaxed">
            {result.text || '(no fused output)'}
          </pre>
        </div>
      </div>

      {!!(result.warnings && result.warnings.length) && (
        <div className="px-4 py-2 border-t border-amber-100 bg-amber-50 text-xs text-amber-800">
          {result.warnings.join(' · ')}
        </div>
      )}
    </div>
  )
}

// ── Parser card ────────────────────────────────────────────────────────────────

function ParserCard({ parser, result, running, selected, viewing, onRun, onSelect, onView, disabled }:
  { parser: ParserDef; result?: ParserResult; running: boolean; selected: boolean; viewing: boolean;
    onRun: () => void; onSelect: () => void; onView: () => void; disabled: boolean }) {

  const done    = result?.status === 'success'
  const errored = result?.status === 'error'

  return (
    <div className={`rounded-xl border-2 p-4 transition-all ${
      selected   ? 'border-indigo-500 bg-indigo-50 shadow-md'
      : done     ? 'border-green-300 bg-green-50'
      : errored  ? 'border-red-300 bg-red-50'
      : running  ? 'border-blue-300 bg-blue-50'
      : CATEGORY_COLORS[parser.category] || 'border-gray-200 bg-white'
    }`}>
      {/* Header */}
      <div className="flex items-start justify-between mb-2">
        <div className="flex items-center gap-1.5">
          <span className={`${parser.category === 'ai' ? 'text-indigo-500' : parser.category === 'ocr' ? 'text-purple-500' : parser.category === 'vlm' ? 'text-pink-500' : 'text-blue-500'}`}>
            {CATEGORY_ICONS[parser.category]}
          </span>
          <span className="text-sm font-bold text-gray-800">{parser.name}</span>
        </div>
        {done && (
          <span className="text-[10px] font-semibold bg-green-100 text-green-700 px-1.5 py-0.5 rounded-full">
            {result!.text_chars.toLocaleString()} chars
          </span>
        )}
      </div>
      <p className="text-xs text-gray-500 mb-3 leading-snug">{parser.desc}</p>

      {/* Error */}
      {errored && (
        <p className="text-xs text-red-500 mb-2 bg-red-100 rounded-lg px-2 py-1 line-clamp-2">{result!.error}</p>
      )}

      {/* Stats */}
      {done && (
        <div className="flex flex-col gap-1.5 mb-3">
          <div className="flex items-center gap-3 text-xs text-gray-500">
            <span className="flex items-center gap-1"><Clock className="w-3 h-3" />{result!.duration_ms.toLocaleString()}ms</span>
            {result!.tables > 0 && <span>{result!.tables} tables</span>}
            {result!.pages_processed != null && (
              <span className="text-pink-600 font-medium">📄 {result!.pages_processed} pages</span>
            )}
            {result!.model && (
              <span className="text-pink-500">🤖 {result!.model}</span>
            )}
          </div>
          {/* Per-page breakdown for VLM and OCR */}
          {result!.page_results && result!.page_results.length > 1 && (
            <div className="bg-gray-50 border border-gray-200 rounded-lg px-2 py-1.5 max-h-32 overflow-y-auto">
              {result!.page_results.map((pg) => (
                <div key={pg.page} className={`flex items-center gap-2 text-[10px] py-0.5 ${pg.status === 'error' ? 'text-red-500' : 'text-gray-600'}`}>
                  <span className="font-mono font-semibold w-10 shrink-0">p.{pg.page}</span>
                  {pg.status === 'success'
                    ? <span className="text-green-700">✓ {(pg.chars ?? pg.lines ?? 0).toLocaleString()} {pg.chars != null ? 'chars' : 'lines'}</span>
                    : <span className="text-red-500">✗ {pg.error}</span>
                  }
                  {pg.duration_ms && <span className="text-gray-400 ml-auto">{pg.duration_ms}ms</span>}
                </div>
              ))}
            </div>
          )}
          {result!.errors && result!.errors.length > 0 && (
            <p className="text-[10px] text-red-500 bg-red-50 rounded px-2 py-1">
              {result!.errors.join(' | ')}
            </p>
          )}
        </div>
      )}

      {/* Actions */}
      <div className="flex gap-2">
        {!done && !running && (
          <button onClick={onRun} disabled={disabled}
            className="flex-1 flex items-center justify-center gap-1.5 bg-white border border-gray-300 text-gray-700 text-xs font-semibold py-2 rounded-lg hover:bg-gray-50 hover:border-gray-400 disabled:opacity-40 disabled:cursor-not-allowed transition-colors">
            <Play className="w-3 h-3" /> Run
          </button>
        )}
        {running && (
          <div className="flex-1 flex items-center justify-center gap-1.5 bg-blue-100 text-blue-700 text-xs font-semibold py-2 rounded-lg">
            <Loader2 className="w-3 h-3 animate-spin" /> Running…
          </div>
        )}
        {done && (
          <>
            <button onClick={onView}
              className={`flex-1 text-xs font-semibold py-2 rounded-lg transition-colors ${
                viewing ? 'bg-gray-800 text-white' : 'bg-white border border-gray-300 text-gray-700 hover:bg-gray-50'
              }`}>
              {viewing ? 'Hide text' : 'View text'}
            </button>
            <button onClick={onSelect}
              className={`flex-1 text-xs font-semibold py-2 rounded-lg transition-colors ${
                selected ? 'bg-indigo-600 text-white' : 'bg-white border border-indigo-300 text-indigo-600 hover:bg-indigo-50'
              }`}>
              {selected ? '✓ Selected' : 'Select'}
            </button>
          </>
        )}
      </div>
    </div>
  )
}

// ── PDF type badge ─────────────────────────────────────────────────────────────

function PdfTypeBadge({ data }: { data: any }) {
  const colors: Record<string, string> = {
    text: 'bg-green-100 border-green-300 text-green-800',
    image: 'bg-orange-100 border-orange-300 text-orange-800',
    mixed: 'bg-yellow-100 border-yellow-300 text-yellow-800',
    encrypted: 'bg-red-100 border-red-300 text-red-800',
  }
  return (
    <div className={`rounded-xl border px-4 py-3 flex flex-wrap items-center gap-4 ${colors[data.type] || 'bg-gray-100 border-gray-300 text-gray-700'}`}>
      <div>
        <span className="text-xs font-bold uppercase tracking-wider">PDF Type: </span>
        <span className="text-sm font-bold">{data.type?.toUpperCase()}</span>
      </div>
      <span className="text-sm">{data.pages} pages · {data.text_pages} text · {data.image_pages} image</span>
      <span className="text-sm flex-1">{data.notes}</span>
      {data.recommended_parsers?.[0] && (
        <span className="text-xs font-semibold bg-white/60 px-2 py-1 rounded-lg">
          Recommended: {data.recommended_parsers[0].parser}
        </span>
      )}
    </div>
  )
}

// ── LLM result view ────────────────────────────────────────────────────────────

// ── V2 Schema Renderer ────────────────────────────────────────────────────────
function V2ResultView({ v2 }: { v2: V2Result }) {
  const [tab, setTab] = useState<'daily'|'calendar'|'overtime'|'validation'|'approval'|'ignored'>('daily')
  const s   = v2.summary
  const ot  = v2.overtime
  const val = v2.validation
  const mgr = v2.manager_approval
  const worked = v2.daily_records.filter(r => r.worked)

  const statusColor = {
    matched: 'bg-green-100 text-green-700',
    mismatch: 'bg-red-100 text-red-700',
    missing_document_total: 'bg-yellow-100 text-yellow-700',
    unclear: 'bg-gray-100 text-gray-700',
  }[val?.validation_status] || 'bg-gray-100 text-gray-700'

  const approvalColor = {
    approved: 'bg-green-100 text-green-700',
    not_found: 'bg-gray-100 text-gray-600',
    unclear: 'bg-yellow-100 text-yellow-700',
  }[mgr?.status] || 'bg-gray-100 text-gray-600'

  return (
    <div className="mt-4 border border-indigo-100 rounded-xl overflow-hidden">
      {/* V2 summary strip */}
      <div className="grid grid-cols-2 sm:grid-cols-4 divide-x divide-y border-b bg-gradient-to-r from-slate-50 to-indigo-50 text-center">
        {[
          { label: 'Worked days',   value: s?.worked_days_count ?? worked.length },
          { label: 'Regular hrs',   value: `${s?.total_regular_hours ?? 0}h` },
          { label: 'Overtime hrs',  value: `${s?.total_overtime_hours ?? 0}h` },
          { label: 'Payable hrs',   value: `${s?.total_payable_hours ?? 0}h`, highlight: true },
          { label: 'Sick hrs',      value: `${s?.total_sick_hours ?? 0}h` },
          { label: 'Vacation hrs',  value: `${s?.total_vacation_hours ?? 0}h` },
          { label: 'Holiday hrs',   value: `${s?.total_holiday_hours ?? 0}h` },
          { label: 'Doc total',     value: s?.document_reported_total_hours != null ? `${s.document_reported_total_hours}h` : '—' },
        ].map(({ label, value, highlight }) => (
          <div key={label} className={`p-3 ${highlight ? 'bg-indigo-50' : ''}`}>
            <p className="text-xs text-gray-400">{label}</p>
            <p className={`text-base font-bold ${highlight ? 'text-indigo-700' : 'text-gray-800'}`}>{value}</p>
          </div>
        ))}
      </div>

      {/* employer + period row */}
      <div className="flex flex-wrap gap-4 px-4 py-3 text-xs text-gray-600 border-b bg-white">
        {v2.employer_name?.value && (
          <span>🏢 <span className="font-semibold">{v2.employer_name.value}</span>
            {' '}<span className="text-gray-400">(conf {Math.round((v2.employer_name.confidence ?? 0)*100)}%)</span>
          </span>
        )}
        {v2.period?.start_date && (
          <span>📅 Period: <span className="font-semibold">{v2.period.start_date} → {v2.period.end_date}</span></span>
        )}
        <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${statusColor}`}>
          {val?.validation_status ?? 'unclear'}
        </span>
        <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${approvalColor}`}>
          approval: {mgr?.status ?? 'not_found'}
        </span>
        {ot?.has_overtime && (
          <span className="px-2 py-0.5 rounded-full bg-orange-100 text-orange-700 text-xs font-medium">
            OT {ot.total_overtime_hours}h
          </span>
        )}
      </div>

      {/* Sub-tabs */}
      <div className="flex border-b bg-gray-50 text-sm">
        {([['daily','Daily Records'],['calendar','Calendar'],['overtime','Overtime'],['validation','Validation'],['approval','Approval'],['ignored','Ignored Dates']] as const).map(([id, label]) => (
          <button key={id} onClick={() => setTab(id)}
            className={`px-4 py-2 font-medium transition-colors ${
              tab === id ? 'border-b-2 border-indigo-600 text-indigo-600 bg-white' : 'text-gray-500 hover:text-gray-700'
            }`}>{label}</button>
        ))}
      </div>

      <div className="p-4">
        {tab === 'daily' && (
          v2.daily_records.length > 0 ? (
            <div className="overflow-x-auto">
              <table className="min-w-full text-xs divide-y divide-gray-200">
                <thead className="bg-gray-50">
                  <tr>
                    {['Date','Day','In','Out','Lunch','Reg','OT','Sick','Vac','Hol','Total','Evidence'].map(h => (
                      <th key={h} className="px-2 py-2 text-left text-gray-500 font-medium whitespace-nowrap">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {v2.daily_records.map((dr, i) => (
                    <tr key={i} className={dr.worked ? 'bg-white' : 'bg-gray-50 text-gray-400'}>
                      <td className="px-2 py-1.5 font-mono font-semibold whitespace-nowrap">{dr.date}</td>
                      <td className="px-2 py-1.5 whitespace-nowrap">{dr.day ?? '—'}</td>
                      <td className="px-2 py-1.5 font-mono whitespace-nowrap">{dr.in_time ?? '—'}</td>
                      <td className="px-2 py-1.5 font-mono whitespace-nowrap">{dr.out_time ?? '—'}</td>
                      <td className="px-2 py-1.5 text-center">{dr.lunch_hours || '—'}</td>
                      <td className="px-2 py-1.5 font-semibold text-blue-700">{dr.regular_hours || '—'}</td>
                      <td className={`px-2 py-1.5 font-semibold ${dr.overtime_hours > 0 ? 'text-orange-600' : 'text-gray-300'}`}>{dr.overtime_hours || '—'}</td>
                      <td className={`px-2 py-1.5 ${dr.sick_hours > 0 ? 'text-purple-600' : 'text-gray-300'}`}>{dr.sick_hours || '—'}</td>
                      <td className={`px-2 py-1.5 ${dr.vacation_hours > 0 ? 'text-teal-600' : 'text-gray-300'}`}>{dr.vacation_hours || '—'}</td>
                      <td className={`px-2 py-1.5 ${dr.holiday_hours > 0 ? 'text-green-600' : 'text-gray-300'}`}>{dr.holiday_hours || '—'}</td>
                      <td className="px-2 py-1.5 font-bold text-gray-800">{dr.total_hours || '—'}</td>
                      <td className="px-2 py-1.5 text-gray-400 max-w-xs truncate" title={dr.evidence ?? ''}>{dr.evidence ?? '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : <p className="text-sm text-gray-400 text-center py-6">No daily records</p>
        )}

        {tab === 'calendar' && (
          <MonthCalendar
            entries={v2ToDayEntries(v2.daily_records)}
            name={v2.employee_name || 'Timesheet'}
            periodStart={v2.period?.start_date}
            periodEnd={v2.period?.end_date}
            subtitle={`${v2.daily_records.filter(r => r.worked).length} worked day(s) · ${v2.summary?.total_payable_hours ?? 0}h payable`}
          />
        )}
        {tab === 'overtime' && (
          <div className="grid grid-cols-2 gap-3">
            {[
              { k: 'Has Overtime',         v: ot?.has_overtime ? '✅ Yes' : '❌ No' },
              { k: 'Daily OT hours',       v: `${ot?.daily_overtime_hours ?? 0}h` },
              { k: 'Weekly OT hours',      v: `${ot?.weekly_overtime_hours ?? 0}h` },
              { k: 'Total OT hours',       v: `${ot?.total_overtime_hours ?? 0}h` },
              { k: 'Policy used',          v: ot?.policy_used || '—' },
            ].map(({ k, v }) => (
              <div key={k} className="bg-orange-50 rounded-xl px-4 py-3">
                <p className="text-xs text-orange-400 mb-0.5">{k}</p>
                <p className="text-sm font-bold text-orange-800">{v}</p>
              </div>
            ))}
          </div>
        )}

        {tab === 'validation' && (
          <div className="space-y-3">
            <div className="grid grid-cols-2 gap-3">
              {[
                { k: 'Validation status',  v: val?.validation_status ?? '—' },
                { k: 'Calculated total',   v: `${val?.calculated_total ?? 0}h` },
                { k: 'Document total',     v: val?.document_total != null ? `${val.document_total}h` : '—' },
              ].map(({ k, v }) => (
                <div key={k} className={`rounded-xl px-4 py-3 ${statusColor}`}>
                  <p className="text-xs opacity-60 mb-0.5">{k}</p>
                  <p className="text-sm font-bold">{v}</p>
                </div>
              ))}
            </div>
            {val?.issues?.length > 0 && (
              <div className="bg-red-50 border border-red-200 rounded-xl p-4">
                <p className="text-xs font-semibold text-red-700 mb-2">Issues detected:</p>
                <ul className="list-disc list-inside space-y-1">
                  {val.issues.map((issue, i) => (
                    <li key={i} className="text-xs text-red-600">{issue}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}

        {tab === 'approval' && (
          <div className="space-y-3">
            <div className="grid grid-cols-2 gap-3">
              {[
                { k: 'Approval status', v: mgr?.status ?? 'not_found' },
                { k: 'Manager name',    v: mgr?.manager_name ?? '—' },
                { k: 'Approval date',   v: mgr?.approval_date ?? '—' },
              ].map(({ k, v }) => (
                <div key={k} className={`rounded-xl px-4 py-3 ${approvalColor}`}>
                  <p className="text-xs opacity-60 mb-0.5">{k}</p>
                  <p className="text-sm font-bold">{v}</p>
                </div>
              ))}
            </div>
            {mgr?.evidence && (
              <div className="bg-gray-50 rounded-xl p-4">
                <p className="text-xs font-semibold text-gray-500 mb-1">Evidence found:</p>
                <p className="text-xs text-gray-700 font-mono whitespace-pre-wrap">{mgr.evidence}</p>
              </div>
            )}
          </div>
        )}

        {tab === 'ignored' && (
          v2.ignored_dates?.length > 0 ? (
            <div className="space-y-2">
              {v2.ignored_dates.map((ig, i) => (
                <div key={i} className="flex items-center gap-3 bg-gray-50 rounded-lg px-4 py-2">
                  <span className="font-mono text-xs font-semibold text-gray-700">{ig.date}</span>
                  <span className="text-xs text-gray-500">{ig.reason}</span>
                </div>
              ))}
            </div>
          ) : <p className="text-sm text-gray-400 text-center py-6">No dates were ignored</p>
        )}
      </div>
    </div>
  )
}

function LLMResultView({ result, parserUsed }: { result: LLMResult; parserUsed: string }) {
  const [tab, setTab] = useState<'summary'|'entries'|'v2'|'prompt'|'source'>('summary')

  if (result.status === 'error') {
    return (
      <div className="bg-red-50 border border-red-300 rounded-2xl p-6">
        <p className="font-semibold text-red-700 mb-1">LLM extraction failed</p>
        <p className="text-sm text-red-600 font-mono break-all">{result.error}</p>
      </div>
    )
  }

  if (result.status === 'skipped') {
    return (
      <div className="bg-amber-50 border border-amber-300 rounded-2xl p-6 flex items-center gap-3">
        <AlertTriangle className="w-5 h-5 text-amber-500" />
        <p className="text-sm text-amber-700">{(result as any).note || 'LLM skipped'}</p>
      </div>
    )
  }

  const s    = result.summary || {}
  const src  = (result as any).source_analysis || {}
  const warn = (result as any).warning
  const incomplete = result.status === 'warning'
  const v2   = result.v2_result

  return (
    <div className="bg-white border border-gray-200 rounded-2xl overflow-hidden shadow-sm">

      {/* Incomplete extraction warning banner */}
      {incomplete && warn && (
        <div className="flex items-start gap-3 px-5 py-4 bg-amber-50 border-b border-amber-200">
          <AlertTriangle className="w-5 h-5 text-amber-500 mt-0.5 shrink-0" />
          <div>
            <p className="text-sm font-semibold text-amber-800">Incomplete Extraction</p>
            <p className="text-xs text-amber-700 mt-0.5">{warn}</p>
          </div>
        </div>
      )}

      {/* Validation passed badge */}
      {!incomplete && s.src_candidate_rows > 0 && (
        <div className="flex items-center gap-2 px-5 py-3 bg-green-50 border-b border-green-200">
          <Check className="w-4 h-4 text-green-600" />
          <p className="text-xs text-green-700 font-medium">
            Validation passed — {s.entries_found} entries extracted from {s.src_candidate_rows} detected source rows
            ({s.completeness_pct}%)
          </p>
        </div>
      )}

      {/* Result header */}
      <div className="px-6 py-5 border-b bg-gradient-to-r from-indigo-50 to-purple-50">
        <div className="flex items-start justify-between">
          <div>
            <p className={`text-sm font-bold uppercase tracking-wider mb-1 ${incomplete ? 'text-amber-600' : 'text-gray-500'}`}>
              {incomplete ? 'Extraction Incomplete' : 'Extraction Complete'}
            </p>
            <p className="text-2xl font-black text-indigo-700">
              {v2 ? v2.daily_records.filter(r => r.worked).length : (s.entries_found ?? 0)} worked days
            </p>
            {(result.employee_name || v2?.employee_name) && (
              <p className="text-sm text-gray-600 mt-1">
                Employee: <span className="font-semibold">{result.employee_name || v2?.employee_name}</span>
              </p>
            )}
            {v2?.employer_name?.value && (
              <p className="text-sm text-gray-500 mt-0.5">
                Employer: <span className="font-medium">{v2.employer_name.value}</span>
              </p>
            )}
          </div>
          <div className="text-right">
            <p className="text-3xl font-black text-green-600">
              {v2 ? v2.summary.total_payable_hours : (s.total_hours ?? 0)}h
            </p>
            <p className="text-xs text-gray-400">payable hours</p>
            {(v2 ? v2.summary.total_regular_hours : s.regular_hours) > 0 && (
              <p className="text-xs text-gray-400">
                {v2 ? v2.summary.total_regular_hours : s.regular_hours}h reg
                {' + '}{v2 ? v2.summary.total_overtime_hours : s.overtime_hours}h OT
              </p>
            )}
          </div>
        </div>
        <div className="flex flex-wrap gap-4 mt-4 text-sm text-gray-600">
          {v2?.period?.start_date && (
            <span>📅 {v2.period.start_date} → {v2.period.end_date}</span>
          )}
          {!v2?.period?.start_date && s.period_start && s.period_end && (
            <span>📅 Period: {s.period_start} → {s.period_end}</span>
          )}
          {v2 && (
            <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${
              v2.validation.validation_status === 'matched' ? 'bg-green-100 text-green-700' :
              v2.validation.validation_status === 'mismatch' ? 'bg-red-100 text-red-700' :
              'bg-yellow-100 text-yellow-700'
            }`}>{v2.validation.validation_status}</span>
          )}
          {v2 && (
            <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${
              v2.manager_approval.status === 'approved' ? 'bg-green-100 text-green-700' :
              v2.manager_approval.status === 'unclear' ? 'bg-yellow-100 text-yellow-700' :
              'bg-gray-100 text-gray-500'
            }`}>👤 {v2.manager_approval.status}</span>
          )}
          <span>⚡ {result.duration_ms.toLocaleString()}ms</span>
          <span>🤖 {result.model}</span>
          <span>📄 via {parserUsed}</span>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex border-b overflow-x-auto">
        {([['summary','Summary'],['entries','Entries'],
          ...(v2 ? [['v2','V2 Schema']] as const : []),
          ['source','Source Analysis'],['prompt','Prompt']] as [string,string][]).map(([id, label]) => (
          <button key={id} onClick={() => setTab(id as any)}
            className={`px-5 py-3 text-sm font-medium transition-colors whitespace-nowrap ${
              tab === id ? 'border-b-2 border-indigo-600 text-indigo-600' : 'text-gray-500 hover:text-gray-800'
            }`}>{label}{id === 'v2' ? ' ✨' : ''}</button>
        ))}
      </div>

      <div className="p-5">
        {tab === 'summary' && (
          <div className="grid grid-cols-2 gap-3">
            {[
              { k: 'Entries / Worked days', v: v2 ? `${v2.daily_records.filter(r=>r.worked).length} of ${v2.daily_records.length}` : s.entries_found },
              { k: 'Total payable hours',   v: v2 ? `${v2.summary.total_payable_hours}h` : (s.total_hours ? `${s.total_hours}h` : '—') },
              { k: 'Regular hours',         v: v2 ? `${v2.summary.total_regular_hours}h` : (s.regular_hours ? `${s.regular_hours}h` : '—') },
              { k: 'Overtime hours',        v: v2 ? `${v2.summary.total_overtime_hours}h` : (s.overtime_hours ? `${s.overtime_hours}h` : '0h') },
              { k: 'Sick hours',            v: v2 ? `${v2.summary.total_sick_hours}h` : (s.sick_hours ? `${s.sick_hours}h` : '—') },
              { k: 'Vacation hours',        v: v2 ? `${v2.summary.total_vacation_hours}h` : (s.vacation_hours ? `${s.vacation_hours}h` : '—') },
              { k: 'Period start',          v: v2?.period?.start_date || s.period_start || '—' },
              { k: 'Period end',            v: v2?.period?.end_date   || s.period_end   || '—' },
              { k: 'Employee name',         v: result.employee_name || v2?.employee_name || '—' },
              { k: 'Employer name',         v: v2?.employer_name?.value || '—' },
              { k: 'Manager approval',      v: v2 ? v2.manager_approval.status : (s.manager_approval || '—') },
              { k: 'Validation',            v: v2 ? v2.validation.validation_status : (s.validation_passed ? '✅ Passed' : '⚠️ Incomplete') },
              { k: 'Source rows detected',  v: src.detected_source_row_count ?? '—' },
              { k: 'Completeness',          v: s.completeness_pct != null ? `${s.completeness_pct}%` : '—' },
              { k: 'Period filter',         v: s.period_filter || 'None (all dates)' },
              { k: 'Parser used',           v: parserUsed },
            ].map(({ k, v }) => (
              <div key={k} className="rounded-xl px-4 py-3 bg-gray-50">
                <p className="text-xs text-gray-400 mb-0.5">{k}</p>
                <p className="text-sm font-bold text-gray-800">{v}</p>
              </div>
            ))}
          </div>
        )}

        {tab === 'entries' && (
          result.entries.length > 0
            ? <EntriesTable entries={result.entries} />
            : <p className="text-sm text-gray-400 text-center py-8">No entries extracted</p>
        )}

        {tab === 'v2' && v2 && <V2ResultView v2={v2} />}

        {tab === 'source' && (
          <div className="space-y-3">
            <div className="grid grid-cols-2 gap-3">
              {[
                { k: 'Candidate data rows',    v: src.detected_source_row_count ?? '—' },
                { k: 'Weekly sections found',  v: src.detected_weekly_section_count ?? '—' },
                { k: 'Dates found in source',  v: src.date_count ?? '—' },
                { k: 'Source date range',      v: src.detected_date_range_from_source || '—' },
                { k: 'Extraction blocks used', v: s.block_count ?? 1 },
                { k: 'Strategy',               v: s.extraction_strategy || '—' },
              ].map(({ k, v }) => (
                <div key={k} className="bg-blue-50 rounded-xl px-4 py-3">
                  <p className="text-xs text-blue-400 mb-0.5">{k}</p>
                  <p className="text-sm font-bold text-blue-800">{v}</p>
                </div>
              ))}
            </div>
            {incomplete && (
              <div className="bg-amber-50 border border-amber-200 rounded-xl p-4 text-sm text-amber-800">
                <p className="font-semibold mb-1">Why this might be incomplete:</p>
                <ul className="list-disc list-inside space-y-1 text-xs">
                  <li>The parser may have extracted partial text (check Step 2 output)</li>
                  <li>The LLM may have run out of output tokens mid-response</li>
                  <li>The document may have an unusual date/time format not detected</li>
                  <li>Try a different parser in Step 2 (pdfplumber or marker usually work best)</li>
                </ul>
              </div>
            )}
          </div>
        )}

        {tab === 'prompt' && (
          <div className="relative">
            <CopyButton text={result.prompt_preview} className="absolute top-2 right-2 z-10" />
            <pre className="bg-gray-900 text-gray-200 text-xs font-mono rounded-xl p-4 overflow-auto max-h-96 leading-relaxed whitespace-pre-wrap">
              {result.prompt_preview}
            </pre>
          </div>
        )}
      </div>
    </div>
  )
}

// ── Entries table ──────────────────────────────────────────────────────────────

// ── Model Manager ──────────────────────────────────────────────────────────────

function ModelManager({ models, selectedModels, onToggleModel, pullingModel, pullProgress,
  warmingModel, onPull, onWarmup, benchMode, modelRunStatus }: {
  models: ModelDef[]; selectedModels: Set<string>
  onToggleModel: (id: string) => void
  pullingModel: string | null; pullProgress: Record<string, string>
  warmingModel: string | null
  onPull: (id: string) => void; onWarmup: (id: string) => void
  benchMode: boolean
  modelRunStatus?: Record<string, ModelRunStatus>
}) {
  const [expanded, setExpanded] = useState(true)

  return (
    <div className="bg-white border border-gray-200 rounded-2xl overflow-hidden">
      <button onClick={() => setExpanded(e => !e)}
        className="w-full flex items-center justify-between px-5 py-4 hover:bg-gray-50 transition-colors">
        <div className="flex items-center gap-2">
          <Cpu className="w-4 h-4 text-indigo-500" />
          <span className="font-semibold text-gray-800 text-sm">Model Library</span>
          <span className="text-xs bg-indigo-100 text-indigo-700 rounded-full px-2 py-0.5">
            {models.filter(m => m.pulled).length}/{models.length} pulled
          </span>
          {benchMode && (
            <span className="text-xs bg-purple-100 text-purple-700 rounded-full px-2 py-0.5">
              {selectedModels.size} selected for benchmark
            </span>
          )}
        </div>
        {expanded ? <ChevronUp className="w-4 h-4 text-gray-400" /> : <ChevronDown className="w-4 h-4 text-gray-400" />}
      </button>

      {expanded && (
        <div className="divide-y divide-gray-100">
          {models.map(m => {
            const isPulling  = pullingModel === m.id
            const isWarming  = warmingModel === m.id
            const isSelected = selectedModels.has(m.id)
            const progress   = pullProgress[m.id]
            const runState   = modelRunStatus?.[m.id]

            return (
              <div key={m.id} className={`px-5 py-3 flex items-center gap-3 transition-colors ${
                isSelected && benchMode ? 'bg-purple-50' : m.default ? 'bg-indigo-50' : ''
              }`}>
                {/* Checkbox (benchmark mode) or radio indicator */}
                {benchMode ? (
                  <input type="checkbox" checked={isSelected} onChange={() => onToggleModel(m.id)}
                    disabled={!m.pulled}
                    className="w-4 h-4 text-purple-600 rounded cursor-pointer disabled:opacity-40" />
                ) : (
                  <button onClick={() => m.pulled && onToggleModel(m.id)}
                    className={`w-4 h-4 rounded-full border-2 transition-colors ${
                      isSelected && m.pulled ? 'bg-indigo-600 border-indigo-600' : 'border-gray-300'
                    } ${!m.pulled ? 'opacity-40 cursor-not-allowed' : 'cursor-pointer'}`} />
                )}

                {/* Model info */}
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-sm font-semibold text-gray-800">{m.name}</span>
                    <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded-full ${ROLE_COLORS[m.role] || 'bg-gray-100 text-gray-600'}`}>
                      {m.role.replace('_', ' ')}
                    </span>
                    {m.default && <span className="text-[10px] font-semibold bg-indigo-100 text-indigo-700 px-1.5 py-0.5 rounded-full">default</span>}
                    {m.design_doc && (
                      <span className="text-[10px] text-gray-400 font-mono">{m.design_doc}</span>
                    )}
                  </div>
                  <p className="text-xs text-gray-500 mt-0.5">{m.description}</p>
                  {isPulling && progress && (
                    <p className="text-xs text-blue-600 mt-1 font-medium">{progress}</p>
                  )}
                  {/* Live bench run status inline */}
                  {runState?.state === 'running' && (
                    <p className="text-xs text-blue-600 mt-1 font-medium flex items-center gap-1">
                      <Loader2 className="w-3 h-3 animate-spin" /> Running…
                    </p>
                  )}
                  {runState?.state === 'done' && runState.result && (
                    <p className="text-xs text-green-600 mt-1 font-medium">
                      ✓ {runState.result.summary?.entries_found ?? 0} entries · {runState.result.summary?.total_hours ?? 0}h · {(runState.result.duration_ms/1000).toFixed(1)}s
                    </p>
                  )}
                  {runState?.state === 'error' && (
                    <p className="text-xs text-red-500 mt-1">{runState.error || 'failed'}</p>
                  )}
                </div>

                {/* Size */}
                <span className="text-xs text-gray-400 whitespace-nowrap">{m.size_gb} GB</span>

                {/* Status + actions */}
                <div className="flex items-center gap-1.5">
                  {/* Live bench indicator takes precedence when running */}
                  {runState?.state === 'running' ? (
                    <span className="flex items-center gap-1 text-[10px] font-semibold text-blue-700 bg-blue-100 px-2 py-0.5 rounded-full animate-pulse">
                      <Loader2 className="w-3 h-3 animate-spin" /> Running
                    </span>
                  ) : runState?.state === 'done' ? (
                    <span className="flex items-center gap-1 text-[10px] font-semibold text-green-700 bg-green-100 px-2 py-0.5 rounded-full">
                      <CheckCircle2 className="w-3 h-3" /> Done
                    </span>
                  ) : runState?.state === 'error' ? (
                    <span className="flex items-center gap-1 text-[10px] font-semibold text-red-700 bg-red-100 px-2 py-0.5 rounded-full">
                      <XCircle className="w-3 h-3" /> Error
                    </span>
                  ) : m.pulled ? (
                    <>
                      <span className="flex items-center gap-1 text-[10px] font-semibold text-green-700 bg-green-100 px-2 py-0.5 rounded-full">
                        <Check className="w-3 h-3" /> Ready
                      </span>
                      <button onClick={() => onWarmup(m.id)} disabled={isWarming || isPulling}
                        className="text-[10px] text-amber-700 bg-amber-100 hover:bg-amber-200 px-2 py-0.5 rounded-full font-semibold disabled:opacity-50 transition-colors whitespace-nowrap">
                        {isWarming ? <Loader2 className="w-3 h-3 animate-spin" /> : '🔥 Warm up'}
                      </button>
                    </>
                  ) : (
                    <button onClick={() => onPull(m.id)} disabled={isPulling || !!pullingModel}
                      className="flex items-center gap-1 text-[10px] text-blue-700 bg-blue-100 hover:bg-blue-200 px-2 py-1 rounded-full font-semibold disabled:opacity-50 transition-colors whitespace-nowrap">
                      {isPulling ? <><Loader2 className="w-3 h-3 animate-spin" /> Pulling…</> : <><Download className="w-3 h-3" /> Pull</>}
                    </button>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

// ── Benchmark Results ───────────────────────────────────────────────────────────

function BenchmarkView({ result }: { result: BenchmarkResult }) {
  const [expandedModel, setExpandedModel] = useState<string | null>(result.best_model)

  const sorted = [...result.results].sort((a, b) => (b._score ?? 0) - (a._score ?? 0))

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="bg-gradient-to-r from-purple-50 to-indigo-50 border border-purple-200 rounded-2xl px-6 py-5">
        <div className="flex items-start justify-between">
          <div>
            <p className="text-sm font-bold text-purple-500 uppercase tracking-wider mb-1">Benchmark Complete</p>
            <p className="text-2xl font-black text-purple-700">{result.models_run} models compared</p>
            {result.best_model && (
              <div className="flex items-center gap-2 mt-2">
                <Trophy className="w-4 h-4 text-amber-500" />
                <p className="text-sm text-gray-700">Best: <span className="font-bold text-amber-700">{result.best_model}</span></p>
              </div>
            )}
          </div>
          <div className="text-right">
            <p className="text-2xl font-black text-indigo-600">{(result.duration_ms / 1000).toFixed(1)}s</p>
            <p className="text-xs text-gray-400">total time</p>
          </div>
        </div>
      </div>

      {/* Comparison table */}
      <div className="bg-white border border-gray-200 rounded-2xl overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead className="bg-gray-50 border-b">
              <tr>
                <th className="text-left px-4 py-3 font-semibold text-gray-600 whitespace-nowrap">Model</th>
                <th className="text-right px-3 py-3 font-semibold text-gray-600">Entries</th>
                <th className="text-right px-3 py-3 font-semibold text-gray-600">Total Hours</th>
                <th className="text-right px-3 py-3 font-semibold text-gray-600">Completeness</th>
                <th className="text-right px-3 py-3 font-semibold text-gray-600">Period</th>
                <th className="text-right px-3 py-3 font-semibold text-gray-600">Latency</th>
                <th className="text-right px-3 py-3 font-semibold text-gray-600">Score</th>
              </tr>
            </thead>
            <tbody>
              {sorted.map((r, i) => {
                const s = r.summary || {}
                const isWinner = r._recommended
                const isError  = r.status !== 'success'
                return (
                  <tr key={r.model_id}
                    onClick={() => setExpandedModel(expandedModel === r.model_id ? null : r.model_id)}
                    className={`border-b cursor-pointer transition-colors ${
                      isWinner ? 'bg-amber-50 hover:bg-amber-100' : 'hover:bg-gray-50'
                    }`}>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        {isWinner && <Trophy className="w-3.5 h-3.5 text-amber-500 shrink-0" />}
                        <span className={`font-semibold ${isWinner ? 'text-amber-800' : 'text-gray-800'}`}>{r.model_id}</span>
                        {isError && <XCircle className="w-3.5 h-3.5 text-red-500" />}
                      </div>
                    </td>
                    <td className={`px-3 py-3 text-right font-mono ${isError ? 'text-red-400' : 'text-gray-800 font-bold'}`}>
                      {isError ? '—' : r.v2_result ? r.v2_result.daily_records.filter(d => d.worked).length : (s.entries_found ?? 0)}
                    </td>
                    <td className="px-3 py-3 text-right font-mono text-gray-700">
                      {isError ? '—' : r.v2_result ? `${r.v2_result.summary.total_payable_hours}h` : `${s.total_hours ?? 0}h`}
                    </td>
                    <td className="px-3 py-3 text-right">
                      {!isError && s.completeness_pct != null ? (
                        <span className={`font-semibold ${s.completeness_pct >= 80 ? 'text-green-600' : s.completeness_pct >= 50 ? 'text-amber-600' : 'text-red-500'}`}>
                          {s.completeness_pct}%
                        </span>
                      ) : r.v2_result ? (
                        <span className="px-1 py-0.5 rounded text-xs font-medium bg-green-100 text-green-700">v2 ✓</span>
                      ) : '—'}
                    </td>
                    <td className="px-3 py-3 text-right text-gray-500 font-mono text-[10px] whitespace-nowrap">
                      {!isError && r.v2_result?.period?.start_date
                        ? `${r.v2_result.period.start_date} → ${r.v2_result.period.end_date}`
                        : !isError && s.period_start ? `${s.period_start} → ${s.period_end}` : '—'}
                    </td>
                    <td className="px-3 py-3 text-right text-gray-500">
                      {(r.duration_ms / 1000).toFixed(1)}s
                    </td>
                    <td className="px-3 py-3 text-right">
                      <span className={`font-bold ${i === 0 ? 'text-amber-600' : 'text-gray-500'}`}>
                        {r._score != null ? r._score.toFixed(0) : '—'}
                      </span>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* Expanded model entries */}
      {sorted.map(r => expandedModel === r.model_id && (
        <div key={r.model_id} className="bg-white border border-gray-200 rounded-2xl overflow-hidden">
          <div className="px-5 py-3 bg-gray-50 border-b flex items-center justify-between">
            <p className="font-semibold text-sm text-gray-700">
              {r.model_id} — {r.v2_result
                ? `${r.v2_result.daily_records.filter(d => d.worked).length} worked days`
                : `${r.entries.length} entries`}
            </p>
            {(r.employee_name || r.v2_result?.employee_name) && (
              <p className="text-xs text-gray-500">Employee: {r.employee_name || r.v2_result?.employee_name}</p>
            )}
          </div>
          {r.error ? (
            <div className="p-5 text-sm text-red-600 bg-red-50">{r.error}</div>
          ) : r.v2_result ? (
            <div className="p-4">
              <V2ResultView v2={r.v2_result} />
            </div>
          ) : r.entries.length > 0 ? (
            <EntriesTable entries={r.entries} />
          ) : (
            <p className="p-5 text-sm text-gray-400 text-center">No entries extracted</p>
          )}
        </div>
      ))}
    </div>
  )
}

function EntriesTable({ entries }: { entries: any[] }) {
  const keys = Array.from(new Set(entries.flatMap(e => Object.keys(e)).filter(k => !k.startsWith('_'))))
  const priority = ['date','day','start_time','end_time','hours','regular_hours','overtime_hours','notes','employee_name']
  const sorted = [...priority.filter(k => keys.includes(k)), ...keys.filter(k => !priority.includes(k))]

  return (
    <div className="overflow-auto rounded-xl border border-gray-200">
      <table className="w-full text-xs">
        <thead className="bg-gray-50 border-b border-gray-200">
          <tr>{sorted.map(k => <th key={k} className="text-left px-3 py-2 font-semibold text-gray-600 whitespace-nowrap">{k}</th>)}</tr>
        </thead>
        <tbody>
          {entries.map((e, i) => (
            <tr key={i} className="border-b border-gray-100 hover:bg-gray-50">
              {sorted.map(k => (
                <td key={k} className="px-3 py-2 text-gray-700 whitespace-nowrap">
                  {e[k] !== null && e[k] !== undefined ? String(e[k]) : <span className="text-gray-300">—</span>}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ── Copy button ────────────────────────────────────────────────────────────────

function CopyButton({ text, className = '' }: { text: string; className?: string }) {
  const [copied, setCopied] = useState(false)
  return (
    <button onClick={() => { navigator.clipboard.writeText(text); setCopied(true); setTimeout(() => setCopied(false), 2000) }}
      className={`flex items-center gap-1 text-xs text-gray-400 hover:text-white bg-gray-800 px-2 py-1 rounded-md ${className}`}>
      {copied ? <Check className="w-3 h-3" /> : <Copy className="w-3 h-3" />}
      {copied ? 'Copied' : 'Copy'}
    </button>
  )
}
