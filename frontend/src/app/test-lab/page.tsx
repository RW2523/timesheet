'use client'
import { useState, useCallback, useRef } from 'react'
import axios from 'axios'
import {
  Upload, ChevronRight, CheckCircle2, XCircle, Loader2,
  FileText, Search, Brain, Zap, Camera, BarChart3, Copy,
  Check, Clock, ArrowRight, RotateCcw, FlaskConical,
  Layers, AlertTriangle, Play, Send,
} from 'lucide-react'

const API = '/api/v1/debug/lab'

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
  text: string; text_chars: number; tables: number; error?: string; vlm_entries?: any[]
}
interface LLMResult {
  status: 'success'|'error'|'skipped'; duration_ms: number
  provider: string; model: string; employee_name?: string
  entries: any[]; summary: any; prompt_preview: string; error?: string
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

  // Step 3
  const [llmResult, setLLMResult]   = useState<LLMResult | null>(null)
  const [runningLLM, setRunningLLM] = useState(false)

  const reset = () => {
    setStep(1); setUploadResult(null); setParserResults({})
    setRunningParser(null); setSelectedParser(null); setViewingParser(null)
    setLLMResult(null); setRunningLLM(false)
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
          // The slow parsers (VLM, Docling) stream keep-alive newlines then JSON.
          // transformResponse strips those newlines and parses the final JSON.
          transformResponse: [(raw: string) => {
            if (!raw) return raw
            const trimmed = raw.trim()
            // Find the last JSON object in the response (after any keep-alive newlines)
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

  // ── Run LLM ────────────────────────────────────────────────────────────────
  const runLLM = async () => {
    if (!uploadResult || !selectedParser) return
    const pr = parserResults[selectedParser]
    if (!pr || !pr.text) return
    setRunningLLM(true); setStep(3); setLLMResult(null)
    try {
      const { data } = await axios.post<LLMResult>(
        `${API}/${uploadResult.session_id}/run-llm`,
        { text: pr.text, parser_used: selectedParser },
        { timeout: 300000 }
      )
      setLLMResult(data)
    } catch (e: any) {
      setLLMResult({ status: 'error', duration_ms: 0, provider: '', model: '',
        entries: [], summary: {}, prompt_preview: '',
        error: e.response?.data?.detail || e.message })
    } finally { setRunningLLM(false) }
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
            <>
              <button key={n}
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
            </>
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
          <div className="max-w-2xl mx-auto">
            <h2 className="text-xl font-bold text-gray-800 mb-1">Upload a file</h2>
            <p className="text-sm text-gray-500 mb-6">Supports PDF, Excel, CSV, Word, PNG, JPG, TIFF</p>
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
        )}

        {/* ── STEP 2: Parsers ──────────────────────────────────────────────── */}
        {step === 2 && uploadResult && (
          <div className="space-y-5">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-xl font-bold text-gray-800">Select a parser</h2>
                <p className="text-sm text-gray-500">Click any parser to run it · select the best result · send to LLM</p>
              </div>
              {selectedResult?.status === 'success' && (
                <button onClick={runLLM}
                  className="flex items-center gap-2 bg-indigo-600 text-white px-5 py-2.5 rounded-xl font-semibold hover:bg-indigo-700 transition-colors shadow-sm">
                  <Send className="w-4 h-4" /> Send to LLM
                  <span className="text-indigo-200 text-xs">({selectedParser})</span>
                </button>
              )}
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
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-xl font-bold text-gray-800">LLM Extraction</h2>
                <p className="text-sm text-gray-500">
                  Feeding <span className="font-semibold text-indigo-600">{selectedParser}</span> output into the LLM
                </p>
              </div>
              <button onClick={() => setStep(2)}
                className="text-xs text-gray-500 hover:text-gray-800 bg-gray-100 hover:bg-gray-200 px-3 py-1.5 rounded-lg transition-colors">
                ← Back to parsers
              </button>
            </div>

            {runningLLM && (
              <div className="bg-white border border-indigo-200 rounded-2xl p-8 text-center">
                <Loader2 className="w-10 h-10 text-indigo-500 mx-auto mb-3 animate-spin" />
                <p className="text-sm font-medium text-indigo-700">LLM is extracting timesheet data…</p>
                <p className="text-xs text-gray-400 mt-1">This may take 30–120 seconds</p>
              </div>
            )}

            {llmResult && !runningLLM && (
              <LLMResultView result={llmResult} parserUsed={selectedParser || ''} />
            )}
          </div>
        )}
      </div>
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
        <div className="flex items-center gap-3 text-xs text-gray-500 mb-3">
          <span className="flex items-center gap-1"><Clock className="w-3 h-3" />{result!.duration_ms.toLocaleString()}ms</span>
          {result!.tables > 0 && <span>{result!.tables} tables</span>}
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

function LLMResultView({ result, parserUsed }: { result: LLMResult; parserUsed: string }) {
  const [tab, setTab] = useState<'summary'|'entries'|'prompt'>('summary')

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

  const s = result.summary || {}

  return (
    <div className="bg-white border border-gray-200 rounded-2xl overflow-hidden shadow-sm">
      {/* Result header */}
      <div className="px-6 py-5 border-b bg-gradient-to-r from-indigo-50 to-purple-50">
        <div className="flex items-start justify-between">
          <div>
            <p className="text-sm font-bold text-gray-500 uppercase tracking-wider mb-1">Extraction Complete</p>
            <p className="text-2xl font-black text-indigo-700">{s.entries_found ?? 0} entries found</p>
            {result.employee_name && (
              <p className="text-sm text-gray-600 mt-1">Employee: <span className="font-semibold">{result.employee_name}</span></p>
            )}
          </div>
          <div className="text-right">
            <p className="text-3xl font-black text-green-600">{s.total_hours ?? 0}h</p>
            <p className="text-xs text-gray-400">total hours</p>
          </div>
        </div>
        <div className="flex flex-wrap gap-4 mt-4 text-sm text-gray-600">
          {s.date_range && s.date_range !== 'not detected' && (
            <span>📅 {s.date_range}</span>
          )}
          {s.unique_dates > 0 && <span>📋 {s.unique_dates} unique days</span>}
          <span>⚡ {result.duration_ms.toLocaleString()}ms</span>
          <span>🤖 {result.model} ({result.provider})</span>
          <span>📄 via {parserUsed}</span>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex border-b">
        {[['summary','Summary'],['entries','Entries'],['prompt','Prompt']] .map(([id, label]) => (
          <button key={id} onClick={() => setTab(id as any)}
            className={`px-5 py-3 text-sm font-medium transition-colors ${
              tab === id ? 'border-b-2 border-indigo-600 text-indigo-600' : 'text-gray-500 hover:text-gray-800'
            }`}>{label}</button>
        ))}
      </div>

      <div className="p-5">
        {tab === 'summary' && (
          <div className="grid grid-cols-2 gap-3">
            {[
              { k: 'Entries found',  v: s.entries_found },
              { k: 'Total hours',    v: s.total_hours ? `${s.total_hours}h` : '—' },
              { k: 'Date range',     v: s.date_range || '—' },
              { k: 'Unique days',    v: s.unique_dates ?? '—' },
              { k: 'Employee name',  v: result.employee_name || '—' },
              { k: 'Parser used',    v: parserUsed },
            ].map(({ k, v }) => (
              <div key={k} className="bg-gray-50 rounded-xl px-4 py-3">
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

function EntriesTable({ entries }: { entries: any[] }) {
  const keys = Array.from(new Set(entries.flatMap(e => Object.keys(e)).filter(k => !k.startsWith('_'))))
  const priority = ['date','day','start_time','end_time','hours','regular_hours','overtime_hours','notes','employee_name']
  const sorted = [...priority.filter(k => keys.includes(k)), ...keys.filter(k => !priority.includes(k))].slice(0,8)

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
