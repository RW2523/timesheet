'use client'
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { listEmployees, listVendors, listPayrollPeriods, getInactiveEmployees, clearBatchData, clearAllData } from '@/lib/api'
import { Settings, Users, Building2, Calendar, AlertOctagon, Plus, Clock, Trash2, ShieldAlert, TriangleAlert, Mail, ExternalLink, RefreshCw, Play, CheckCircle2, XCircle, Loader2, ChevronDown, ChevronRight } from 'lucide-react'
import axios from 'axios'
import { useRouter, useSearchParams } from 'next/navigation'
import { Suspense } from 'react'

const BASE = '/api/v1'

type Tab = 'employees' | 'vendors' | 'periods' | 'inactive' | 'email' | 'danger'

export default function AdminPage() {
  const [tab, setTab] = useState<Tab>('employees')
  const searchParams = typeof window !== 'undefined'
    ? new URLSearchParams(window.location.search)
    : null
  const tabFromUrl = searchParams?.get('tab') as Tab | null

  const activeTab = tabFromUrl || tab

  const tabs: { key: Tab; label: string; icon: React.ReactNode; danger?: boolean }[] = [
    { key: 'employees', label: 'Employees', icon: <Users className="w-4 h-4" /> },
    { key: 'vendors', label: 'Vendors', icon: <Building2 className="w-4 h-4" /> },
    { key: 'periods', label: 'Payroll Periods', icon: <Calendar className="w-4 h-4" /> },
    { key: 'inactive', label: 'Inactive Report', icon: <AlertOctagon className="w-4 h-4" /> },
    { key: 'email', label: 'Email Integration', icon: <Mail className="w-4 h-4" /> },
    { key: 'danger', label: 'Danger Zone', icon: <Trash2 className="w-4 h-4" />, danger: true },
  ]

  return (
    <div className="p-8 max-w-6xl mx-auto">
      <div className="flex items-center gap-3 mb-8">
        <Settings className="w-7 h-7 text-blue-600" />
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Admin Settings</h1>
          <p className="text-sm text-gray-500">Manage master data</p>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex border-b border-gray-200 mb-6 overflow-x-auto">
        {tabs.map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={`flex items-center gap-2 px-5 py-3 text-sm font-medium border-b-2 whitespace-nowrap transition-colors ${
              activeTab === t.key
                ? t.danger ? 'border-red-500 text-red-600' : 'border-blue-500 text-blue-600'
                : t.danger ? 'border-transparent text-red-400 hover:text-red-600' : 'border-transparent text-gray-500 hover:text-gray-700'
            }`}
          >
            {t.icon} {t.label}
          </button>
        ))}
      </div>

      {activeTab === 'employees' && <EmployeesTab />}
      {activeTab === 'vendors' && <VendorsTab />}
      {activeTab === 'periods' && <PeriodsTab />}
      {activeTab === 'inactive' && <InactiveTab />}
      {activeTab === 'email' && <Suspense fallback={<div>Loading…</div>}><EmailTab /></Suspense>}
      {activeTab === 'danger' && <DangerZoneTab />}
    </div>
  )
}

function EmployeesTab() {
  const { data, isLoading, refetch } = useQuery({ queryKey: ['employees'], queryFn: listEmployees })
  const [form, setForm] = useState({ full_name: '', email: '', employee_type: 'CONTRACTOR' })
  const [creating, setCreating] = useState(false)

  const create = async (e: React.FormEvent) => {
    e.preventDefault()
    setCreating(true)
    try {
      await axios.post(`${BASE}/admin/employees`, form)
      refetch()
      setForm({ full_name: '', email: '', employee_type: 'CONTRACTOR' })
    } finally {
      setCreating(false)
    }
  }

  return (
    <div className="space-y-6">
      <form onSubmit={create} className="bg-white border border-gray-200 rounded-xl p-5 flex gap-3 items-end">
        <div className="flex-1">
          <label className="block text-xs font-medium text-gray-600 mb-1">Full Name *</label>
          <input required value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })}
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm" placeholder="John Smith" />
        </div>
        <div className="flex-1">
          <label className="block text-xs font-medium text-gray-600 mb-1">Email</label>
          <input type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })}
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm" placeholder="john@company.com" />
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">Type</label>
          <select value={form.employee_type} onChange={(e) => setForm({ ...form, employee_type: e.target.value })}
            className="border border-gray-300 rounded-lg px-3 py-2 text-sm">
            <option value="CONTRACTOR">Contractor</option>
            <option value="AJACE_INTERNAL">Ajace Internal</option>
            <option value="CLIENT_VENDOR">Client Vendor</option>
          </select>
        </div>
        <button type="submit" disabled={creating}
          className="inline-flex items-center gap-2 bg-blue-600 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-50">
          <Plus className="w-4 h-4" /> Add
        </button>
      </form>

      <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
        {isLoading ? <div className="p-8 text-center text-gray-400">Loading...</div> : (
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b">
              <tr>{['Name', 'Email', 'Type', 'Active'].map((h) => (
                <th key={h} className="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase">{h}</th>
              ))}</tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {data?.items?.map((e) => (
                <tr key={e.id} className="hover:bg-gray-50">
                  <td className="px-4 py-3 font-medium text-gray-800">{e.full_name}</td>
                  <td className="px-4 py-3 text-gray-500">{e.email || '—'}</td>
                  <td className="px-4 py-3 text-gray-500">{e.employee_type || '—'}</td>
                  <td className="px-4 py-3">{e.is_active ? <span className="text-green-600">Active</span> : <span className="text-gray-400">Inactive</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}

function VendorsTab() {
  const { data, isLoading, refetch } = useQuery({ queryKey: ['vendors'], queryFn: listVendors })
  const [form, setForm] = useState({ name: '', overtime_enabled: false })
  const [creating, setCreating] = useState(false)

  const create = async (e: React.FormEvent) => {
    e.preventDefault()
    setCreating(true)
    try {
      await axios.post(`${BASE}/admin/vendors`, form)
      refetch()
      setForm({ name: '', overtime_enabled: false })
    } finally {
      setCreating(false)
    }
  }

  return (
    <div className="space-y-6">
      <form onSubmit={create} className="bg-white border border-gray-200 rounded-xl p-5 flex gap-3 items-end">
        <div className="flex-1">
          <label className="block text-xs font-medium text-gray-600 mb-1">Vendor Name *</label>
          <input required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })}
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm" />
        </div>
        <div className="flex items-center gap-2 pb-1">
          <input type="checkbox" id="ot" checked={form.overtime_enabled}
            onChange={(e) => setForm({ ...form, overtime_enabled: e.target.checked })} />
          <label htmlFor="ot" className="text-sm text-gray-700">OT Enabled</label>
        </div>
        <button type="submit" disabled={creating}
          className="inline-flex items-center gap-2 bg-blue-600 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-50">
          <Plus className="w-4 h-4" /> Add Vendor
        </button>
      </form>

      <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
        {isLoading ? <div className="p-8 text-center text-gray-400">Loading...</div> : (
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b">
              <tr>{['Name', 'Overtime'].map((h) => (
                <th key={h} className="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase">{h}</th>
              ))}</tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {(data as { items: Array<{ id: string; name: string; overtime_enabled: boolean }> })?.items?.map((v) => (
                <tr key={v.id} className="hover:bg-gray-50">
                  <td className="px-4 py-3 font-medium text-gray-800">{v.name}</td>
                  <td className="px-4 py-3">{v.overtime_enabled ? <span className="text-green-600">Allowed</span> : <span className="text-red-500">Disabled</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}

function PeriodsTab() {
  const { data, isLoading, refetch } = useQuery({ queryKey: ['payroll-periods'], queryFn: listPayrollPeriods })
  const [form, setForm] = useState({ period_key: '', start_date: '', end_date: '', cutoff_date: '' })
  const [creating, setCreating] = useState(false)

  const create = async (e: React.FormEvent) => {
    e.preventDefault()
    setCreating(true)
    try {
      await axios.post(`${BASE}/admin/payroll-periods`, form)
      refetch()
      setForm({ period_key: '', start_date: '', end_date: '', cutoff_date: '' })
    } finally {
      setCreating(false)
    }
  }

  return (
    <div className="space-y-6">
      <form onSubmit={create} className="bg-white border border-gray-200 rounded-xl p-5 grid grid-cols-2 md:grid-cols-4 gap-3 items-end">
        {[
          { key: 'period_key', label: 'Period Key', placeholder: '2026-04' },
          { key: 'start_date', label: 'Start Date', placeholder: '2026-04-01' },
          { key: 'end_date', label: 'End Date', placeholder: '2026-04-30' },
          { key: 'cutoff_date', label: 'Cutoff Date', placeholder: '2026-05-05' },
        ].map(({ key, label, placeholder }) => (
          <div key={key}>
            <label className="block text-xs font-medium text-gray-600 mb-1">{label} *</label>
            <input required value={(form as Record<string, string>)[key]}
              onChange={(e) => setForm({ ...form, [key]: e.target.value })}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm" placeholder={placeholder} />
          </div>
        ))}
        <button type="submit" disabled={creating} className="col-span-2 md:col-span-4 bg-blue-600 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-50">
          <Plus className="w-4 h-4 inline mr-1" /> Add Period
        </button>
      </form>

      <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
        {isLoading ? <div className="p-8 text-center text-gray-400">Loading...</div> : (
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b">
              <tr>{['Period Key', 'Start', 'End', 'Cutoff', 'Status'].map((h) => (
                <th key={h} className="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase">{h}</th>
              ))}</tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {data?.items?.map((p) => (
                <tr key={p.id} className="hover:bg-gray-50">
                  <td className="px-4 py-3 font-mono font-medium text-gray-800">{p.period_key}</td>
                  <td className="px-4 py-3 text-gray-600">{p.start_date}</td>
                  <td className="px-4 py-3 text-gray-600">{p.end_date}</td>
                  <td className="px-4 py-3 text-gray-600">{p.cutoff_date}</td>
                  <td className="px-4 py-3"><span className={`px-2 py-0.5 rounded text-xs font-medium ${p.status === 'OPEN' ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-600'}`}>{p.status}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}


function InactiveTab() {
  const { data, isLoading } = useQuery({
    queryKey: ['inactive-employees'],
    queryFn: getInactiveEmployees,
  })

  if (isLoading) return <div className="p-12 text-center text-gray-400">Loading inactivity report…</div>

  if (!data?.ready) {
    return (
      <div className="bg-yellow-50 border border-yellow-200 rounded-xl p-8 text-center">
        <Clock className="w-10 h-10 text-yellow-500 mx-auto mb-3" />
        <p className="text-yellow-800 font-semibold text-sm">Not enough data yet</p>
        <p className="text-yellow-700 text-sm mt-1 max-w-md mx-auto">{data?.reason}</p>
        <p className="text-yellow-600 text-xs mt-3">
          This report is generated automatically once you have processed timesheets for at least 2 calendar months.
        </p>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      {/* Summary bar */}
      <div className="bg-red-50 border border-red-200 rounded-xl px-5 py-4 flex items-center justify-between">
        <div>
          <p className="text-red-700 font-semibold text-sm">
            {data.total} employee{data.total !== 1 ? 's' : ''} inactive for {data.threshold_months}+ months
          </p>
          <p className="text-red-600 text-xs mt-0.5">
            Cutoff: {data.cutoff_date} · Out of {data.total_active_employees} active employees
          </p>
        </div>
        <AlertOctagon className="w-6 h-6 text-red-500 shrink-0" />
      </div>

      {data.total === 0 ? (
        <div className="bg-green-50 border border-green-200 rounded-xl p-10 text-center">
          <p className="text-green-700 font-medium">All active employees submitted timesheets within the last {data.threshold_months} months.</p>
        </div>
      ) : (
        <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b">
              <tr>
                {['Employee', 'Email', 'Last Submission', 'Months Inactive', 'Status'].map((h) => (
                  <th key={h} className="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {data.items.map((emp: {
                employee_id: string
                full_name: string
                email?: string
                last_submission?: string
                months_inactive?: number
                never_submitted: boolean
              }) => (
                <tr key={emp.employee_id} className="hover:bg-red-50">
                  <td className="px-4 py-3 font-medium text-gray-800">{emp.full_name}</td>
                  <td className="px-4 py-3 text-gray-500">{emp.email || '—'}</td>
                  <td className="px-4 py-3 text-gray-600">{emp.last_submission || '—'}</td>
                  <td className="px-4 py-3">
                    <span className={`px-2 py-0.5 rounded text-xs font-medium ${
                      emp.never_submitted ? 'bg-red-100 text-red-700' :
                      (emp.months_inactive ?? 0) >= 3 ? 'bg-orange-100 text-orange-700' :
                      'bg-yellow-100 text-yellow-700'
                    }`}>
                      {emp.never_submitted ? 'Never submitted' : `${emp.months_inactive} month${(emp.months_inactive ?? 0) !== 1 ? 's' : ''}`}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <span className="px-2 py-0.5 bg-red-100 text-red-700 rounded text-xs font-medium">INACTIVE</span>
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

// ── Danger Zone ───────────────────────────────────────────────────────────────

type ClearMode = 'batch' | 'all' | null

function DangerZoneTab() {
  const router = useRouter()
  const qc = useQueryClient()
  const [mode, setMode] = useState<ClearMode>(null)
  const [confirmText, setConfirmText] = useState('')
  const [result, setResult] = useState<Record<string, unknown> | null>(null)

  const REQUIRED_BATCH = 'CLEAR BATCHES'
  const REQUIRED_ALL = 'DELETE EVERYTHING'

  const batchMut = useMutation({
    mutationFn: clearBatchData,
    onSuccess: (data) => {
      setResult(data)
      setMode(null)
      setConfirmText('')
      qc.invalidateQueries()
    },
  })

  const allMut = useMutation({
    mutationFn: clearAllData,
    onSuccess: (data) => {
      setResult(data)
      setMode(null)
      setConfirmText('')
      qc.invalidateQueries()
    },
  })

  const isPending = batchMut.isPending || allMut.isPending
  const error = (batchMut.error || allMut.error) as Error | null

  return (
    <div className="space-y-6">
      {/* Warning banner */}
      <div className="flex items-start gap-3 bg-red-50 border border-red-300 rounded-xl px-5 py-4">
        <TriangleAlert className="w-5 h-5 text-red-500 shrink-0 mt-0.5" />
        <div>
          <p className="font-semibold text-red-800 text-sm">These actions are irreversible</p>
          <p className="text-red-700 text-xs mt-1">
            Deleted data cannot be recovered. Use only for resetting a test environment or starting a new payroll cycle.
          </p>
        </div>
      </div>

      {/* Success result */}
      {result && (
        <div className="bg-green-50 border border-green-200 rounded-xl px-5 py-4 text-sm">
          <p className="font-semibold text-green-800 mb-2">Cleared successfully</p>
          <pre className="text-xs text-green-700 bg-green-100 rounded p-3 overflow-auto max-h-40">
            {JSON.stringify(result, null, 2)}
          </pre>
          <button onClick={() => router.push('/batches')} className="mt-3 text-xs text-green-700 underline">
            Go to Batches →
          </button>
        </div>
      )}

      {/* Error */}
      {error && (
        <div className="bg-red-100 border border-red-300 rounded-xl px-5 py-3 text-sm text-red-700">
          {error.message}
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
        {/* Option 1 — Clear batch data only */}
        <div className="border-2 border-orange-200 bg-orange-50 rounded-xl p-5 space-y-3">
          <div className="flex items-center gap-2">
            <ShieldAlert className="w-5 h-5 text-orange-500" />
            <h3 className="font-semibold text-orange-800 text-sm">Clear Batch Data</h3>
          </div>
          <p className="text-orange-700 text-xs">
            Removes all uploaded batches, files, OCR extractions, timesheet submissions, validation errors, and reports.
          </p>
          <p className="text-green-700 text-xs font-medium">
            ✓ Preserves: Employees, Vendors, Payroll Periods, Rates
          </p>
          <button
            onClick={() => { setMode('batch'); setConfirmText('') }}
            className="w-full bg-orange-500 hover:bg-orange-600 text-white text-sm font-medium px-4 py-2 rounded-lg transition-colors"
          >
            Clear Batch Data…
          </button>
        </div>

        {/* Option 2 — Clear everything */}
        <div className="border-2 border-red-300 bg-red-50 rounded-xl p-5 space-y-3">
          <div className="flex items-center gap-2">
            <Trash2 className="w-5 h-5 text-red-500" />
            <h3 className="font-semibold text-red-800 text-sm">Clear ALL Data</h3>
          </div>
          <p className="text-red-700 text-xs">
            Removes everything — all batches AND all master data (employees, vendors, payroll periods, rates).
            The database will be completely empty.
          </p>
          <p className="text-red-600 text-xs font-medium">
            ✗ Deletes all employees, vendors, periods too
          </p>
          <button
            onClick={() => { setMode('all'); setConfirmText('') }}
            className="w-full bg-red-600 hover:bg-red-700 text-white text-sm font-medium px-4 py-2 rounded-lg transition-colors"
          >
            Clear Everything…
          </button>
        </div>
      </div>

      {/* Confirmation dialog */}
      {mode && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-2xl shadow-2xl w-full max-w-md p-6 space-y-4">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-full bg-red-100 flex items-center justify-center shrink-0">
                <Trash2 className="w-5 h-5 text-red-600" />
              </div>
              <div>
                <h3 className="font-bold text-gray-900">
                  {mode === 'batch' ? 'Clear Batch Data?' : 'Delete Everything?'}
                </h3>
                <p className="text-sm text-gray-500">
                  {mode === 'batch' ? 'All batches and processing data will be permanently removed.' : 'The entire database will be wiped clean.'}
                </p>
              </div>
            </div>

            <div className="bg-gray-50 rounded-lg p-3 text-xs text-gray-600 space-y-1">
              {mode === 'batch' ? (
                <>
                  <p>Will delete: batches, files, extractions, submissions, validation errors, reports</p>
                  <p className="text-green-700 font-medium">Will keep: employees, vendors, payroll periods, rates</p>
                </>
              ) : (
                <>
                  <p className="text-red-600 font-medium">Will delete: absolutely everything in the database</p>
                  <p>Employees, vendors, periods, rates, batches — all gone</p>
                </>
              )}
            </div>

            <div>
              <label className="block text-xs font-semibold text-gray-700 mb-1.5">
                Type <code className="bg-gray-200 px-1 rounded font-mono">{mode === 'batch' ? REQUIRED_BATCH : REQUIRED_ALL}</code> to confirm
              </label>
              <input
                type="text"
                value={confirmText}
                onChange={(e) => setConfirmText(e.target.value)}
                placeholder={mode === 'batch' ? REQUIRED_BATCH : REQUIRED_ALL}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm font-mono focus:ring-2 focus:ring-red-400 focus:border-red-400"
                autoFocus
              />
            </div>

            <div className="flex gap-3 pt-1">
              <button
                onClick={() => { setMode(null); setConfirmText('') }}
                className="flex-1 bg-gray-100 hover:bg-gray-200 text-gray-700 text-sm font-medium px-4 py-2 rounded-lg transition-colors"
              >
                Cancel
              </button>
              <button
                disabled={
                  isPending ||
                  (mode === 'batch' && confirmText !== REQUIRED_BATCH) ||
                  (mode === 'all' && confirmText !== REQUIRED_ALL)
                }
                onClick={() => mode === 'batch' ? batchMut.mutate() : allMut.mutate()}
                className={`flex-1 text-white text-sm font-medium px-4 py-2 rounded-lg transition-colors disabled:opacity-40 disabled:cursor-not-allowed ${
                  mode === 'batch' ? 'bg-orange-500 hover:bg-orange-600' : 'bg-red-600 hover:bg-red-700'
                }`}
              >
                {isPending ? 'Deleting…' : mode === 'batch' ? 'Clear Batch Data' : 'Delete Everything'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

// ── Email Integration Tab ─────────────────────────────────────────────────────

interface EmailAccount {
  id: string
  label: string
  email_address: string
  provider: string
  is_active: boolean
  last_crawled_at: string | null
  created_at: string
}

interface CrawlJob {
  id: string
  account_id: string
  account_email: string | null
  period_start: string
  period_end: string
  subject_filter: string | null
  status: 'PENDING' | 'RUNNING' | 'AWAITING_APPROVAL' | 'COMPLETED' | 'FAILED'
  emails_scanned: number
  emails_timesheet: number
  emails_skipped: number
  attachments_saved: number
  batch_id: string | null
  triggered_by: string
  error_message: string | null
  created_at: string
  started_at: string | null
  completed_at: string | null
  pending_approval_count: number
}

function EmailTab() {
  const router = useRouter()
  const qc = useQueryClient()

  const [connectLabel, setConnectLabel] = useState('HR Gmail')
  const [showConnectHelp, setShowConnectHelp] = useState(false)
  const [crawlForm, setCrawlForm] = useState({
    account_id: '',
    period_start: '',
    period_end: '',
    subject_filter: '',
  })
  const [expandedJob, setExpandedJob] = useState<string | null>(null)
  const [reviewJob, setReviewJob] = useState<string | null>(null)  // job being reviewed

  const { data: accounts = [], isLoading: loadingAccounts } = useQuery<EmailAccount[]>({
    queryKey: ['email-accounts'],
    queryFn: async () => (await axios.get(`${BASE}/email/accounts`)).data,
    refetchInterval: 5000,
  })

  const { data: jobs = [], isLoading: loadingJobs } = useQuery<CrawlJob[]>({
    queryKey: ['email-crawl-jobs'],
    queryFn: async () => (await axios.get(`${BASE}/email/crawl-jobs`)).data,
    refetchInterval: 3000,
  })

  // Connect Gmail: fetch auth URL → open in new tab
  const connectGmail = async () => {
    try {
      const res = await axios.get(`${BASE}/email/accounts/gmail/auth-url`, {
        params: { label: connectLabel }
      })
      window.open(res.data.auth_url, '_blank', 'width=500,height=700')
    } catch (err: any) {
      alert(err.response?.data?.detail || 'Failed to get auth URL. Make sure GMAIL_CLIENT_ID and GMAIL_CLIENT_SECRET are set in the backend .env')
    }
  }

  const disconnectMutation = useMutation({
    mutationFn: (id: string) => axios.delete(`${BASE}/email/accounts/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['email-accounts'] }),
  })

  const crawlMutation = useMutation({
    mutationFn: (data: typeof crawlForm) =>
      axios.post(`${BASE}/email/crawl-jobs`, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['email-crawl-jobs'] })
      setCrawlForm({ account_id: '', period_start: '', period_end: '', subject_filter: '' })
    },
    onError: (err: any) => alert(err.response?.data?.detail || 'Failed to start crawl'),
  })

  const retryMutation = useMutation({
    mutationFn: (jobId: string) => axios.post(`${BASE}/email/crawl-jobs/${jobId}/retry`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['email-crawl-jobs'] }),
  })

  const activeAccounts = accounts.filter(a => a.is_active)
  const awaitingApproval = jobs.filter(j => j.status === 'AWAITING_APPROVAL')

  return (
    <div className="space-y-8">

      {/* ── Approval banner ── */}
      {awaitingApproval.length > 0 && (
        <div className="bg-amber-50 border border-amber-300 rounded-xl p-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 bg-amber-100 rounded-full flex items-center justify-center">
              <Mail className="w-4 h-4 text-amber-600" />
            </div>
            <div>
              <p className="font-semibold text-amber-800 text-sm">
                {awaitingApproval.length} crawl job{awaitingApproval.length > 1 ? 's' : ''} waiting for your review
              </p>
              <p className="text-xs text-amber-600">
                Emails were found and classified — confirm which ones to process
              </p>
            </div>
          </div>
          <button
            onClick={() => setReviewJob(awaitingApproval[0].id)}
            className="flex items-center gap-2 bg-amber-600 text-white text-sm font-medium px-4 py-2 rounded-lg hover:bg-amber-700 transition-colors"
          >
            Review & Confirm
          </button>
        </div>
      )}

      {/* ── Review modal ── */}
      {reviewJob && (
        <ReviewModal
          jobId={reviewJob}
          onClose={() => setReviewJob(null)}
          onApproved={(batchId) => {
            setReviewJob(null)
            qc.invalidateQueries({ queryKey: ['email-crawl-jobs'] })
            router.push(`/batches/${batchId}`)
          }}
        />
      )}

      {/* ── Connected Accounts ── */}
      <div className="bg-white border border-gray-200 rounded-xl p-6">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h2 className="text-base font-semibold text-gray-900 flex items-center gap-2">
              <Mail className="w-4 h-4 text-blue-500" /> Connected Gmail Accounts
            </h2>
            <p className="text-xs text-gray-500 mt-0.5">Connect a Gmail inbox to automatically collect timesheet submissions</p>
          </div>
          <button
            onClick={() => setShowConnectHelp(!showConnectHelp)}
            className="text-xs text-blue-600 underline"
          >
            Setup guide
          </button>
        </div>

        {showConnectHelp && (
          <div className="mb-4 bg-blue-50 border border-blue-200 rounded-lg p-4 text-xs text-blue-800 space-y-1.5">
            <p className="font-semibold">One-time Google Cloud setup:</p>
            <ol className="list-decimal list-inside space-y-1 pl-1">
              <li>Go to <a href="https://console.cloud.google.com/apis/credentials" target="_blank" className="underline">Google Cloud Console → Credentials</a></li>
              <li>Create an OAuth 2.0 Client ID (type: Web application)</li>
              <li>Add Authorized JavaScript origin: <code className="bg-blue-100 px-1 rounded">http://localhost:3000</code></li>
              <li>Add Authorized redirect URI: <code className="bg-blue-100 px-1 rounded">http://localhost:3000/admin/email/callback</code></li>
              <li>Add your Gmail to the test users list (OAuth consent screen)</li>
              <li>Copy Client ID &amp; Secret → add to backend <code className="bg-blue-100 px-1 rounded">.env</code></li>
              <li>Restart the backend container</li>
            </ol>
          </div>
        )}

        <div className="flex gap-2 items-end mb-4">
          <div className="flex-1">
            <label className="block text-xs font-medium text-gray-600 mb-1">Account label</label>
            <input
              value={connectLabel}
              onChange={e => setConnectLabel(e.target.value)}
              placeholder="e.g. HR Gmail"
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-blue-400 focus:border-blue-400"
            />
          </div>
          <button
            onClick={connectGmail}
            className="flex items-center gap-2 bg-blue-600 text-white text-sm font-medium px-4 py-2 rounded-lg hover:bg-blue-700 transition-colors"
          >
            <ExternalLink className="w-4 h-4" /> Connect Gmail
          </button>
        </div>

        {loadingAccounts ? (
          <div className="flex items-center gap-2 text-sm text-gray-500 py-4"><Loader2 className="w-4 h-4 animate-spin" /> Loading…</div>
        ) : accounts.length === 0 ? (
          <div className="text-sm text-gray-400 py-4 text-center border-2 border-dashed border-gray-200 rounded-lg">
            No accounts connected yet
          </div>
        ) : (
          <div className="space-y-2">
            {accounts.map(acc => (
              <div key={acc.id} className="flex items-center justify-between bg-gray-50 rounded-lg px-4 py-3">
                <div className="flex items-center gap-3">
                  <div className={`w-2 h-2 rounded-full ${acc.is_active ? 'bg-green-500' : 'bg-gray-400'}`} />
                  <div>
                    <p className="text-sm font-medium text-gray-800">{acc.label}</p>
                    <p className="text-xs text-gray-500">{acc.email_address}</p>
                  </div>
                </div>
                <div className="flex items-center gap-3 text-right">
                  {acc.last_crawled_at && (
                    <span className="text-xs text-gray-400">
                      Last crawled: {new Date(acc.last_crawled_at).toLocaleDateString()}
                    </span>
                  )}
                  <button
                    onClick={() => { if (confirm(`Disconnect ${acc.email_address}?`)) disconnectMutation.mutate(acc.id) }}
                    className="text-xs text-red-500 hover:text-red-700 transition-colors"
                  >
                    Disconnect
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* ── Trigger Crawl ── */}
      <div className="bg-white border border-gray-200 rounded-xl p-6">
        <h2 className="text-base font-semibold text-gray-900 flex items-center gap-2 mb-1">
          <Play className="w-4 h-4 text-green-500" /> Trigger Email Crawl
        </h2>
        <p className="text-xs text-gray-500 mb-4">
          The system will scan your inbox, classify emails, and ask for your confirmation before processing any files.
        </p>

        {activeAccounts.length === 0 ? (
          <div className="text-sm text-amber-700 bg-amber-50 border border-amber-200 rounded-lg p-3">
            Connect a Gmail account above before starting a crawl.
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Gmail Account</label>
              <select
                value={crawlForm.account_id}
                onChange={e => setCrawlForm(f => ({ ...f, account_id: e.target.value }))}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-blue-400"
              >
                <option value="">Select account…</option>
                {activeAccounts.map(a => (
                  <option key={a.id} value={a.id}>{a.label} ({a.email_address})</option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Subject keyword filter (optional)</label>
              <input
                value={crawlForm.subject_filter}
                onChange={e => setCrawlForm(f => ({ ...f, subject_filter: e.target.value }))}
                placeholder="e.g. timesheet"
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-blue-400"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">From date</label>
              <input
                type="date"
                value={crawlForm.period_start}
                onChange={e => setCrawlForm(f => ({ ...f, period_start: e.target.value }))}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-blue-400"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">To date</label>
              <input
                type="date"
                value={crawlForm.period_end}
                onChange={e => setCrawlForm(f => ({ ...f, period_end: e.target.value }))}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-blue-400"
              />
            </div>
            <div className="md:col-span-2 flex justify-end">
              <button
                disabled={!crawlForm.account_id || !crawlForm.period_start || !crawlForm.period_end || crawlMutation.isPending}
                onClick={() => crawlMutation.mutate(crawlForm)}
                className="flex items-center gap-2 bg-green-600 text-white text-sm font-medium px-5 py-2 rounded-lg hover:bg-green-700 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
              >
                {crawlMutation.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4" />}
                Scan Inbox
              </button>
            </div>
          </div>
        )}
      </div>

      {/* ── Crawl Job History ── */}
      <div className="bg-white border border-gray-200 rounded-xl p-6">
        <h2 className="text-base font-semibold text-gray-900 flex items-center gap-2 mb-4">
          <RefreshCw className="w-4 h-4 text-gray-500" /> Crawl Job History
        </h2>

        {loadingJobs ? (
          <div className="flex items-center gap-2 text-sm text-gray-500 py-4"><Loader2 className="w-4 h-4 animate-spin" /> Loading…</div>
        ) : jobs.length === 0 ? (
          <div className="text-sm text-gray-400 py-4 text-center border-2 border-dashed border-gray-200 rounded-lg">
            No crawl jobs yet
          </div>
        ) : (
          <div className="space-y-2">
            {jobs.map(job => (
              <div key={job.id} className="border border-gray-200 rounded-lg overflow-hidden">
                <button
                  onClick={() => setExpandedJob(expandedJob === job.id ? null : job.id)}
                  className="w-full flex items-center justify-between px-4 py-3 hover:bg-gray-50 transition-colors text-left"
                >
                  <div className="flex items-center gap-3">
                    <StatusBadge status={job.status} />
                    <div>
                      <p className="text-sm font-medium text-gray-800">
                        {job.account_email || 'Unknown'} · {job.period_start} to {job.period_end}
                      </p>
                      <p className="text-xs text-gray-500">
                        {new Date(job.created_at).toLocaleString()}
                        {job.subject_filter && ` · Filter: "${job.subject_filter}"`}
                      </p>
                    </div>
                  </div>
                  <div className="flex items-center gap-3 text-xs text-gray-500">
                    <span>{job.emails_scanned} scanned</span>
                    <span className="text-green-600 font-medium">{job.emails_timesheet} timesheets</span>
                    {job.pending_approval_count > 0 && (
                      <span className="bg-amber-100 text-amber-700 px-2 py-0.5 rounded-full font-medium">
                        {job.pending_approval_count} pending review
                      </span>
                    )}
                    {expandedJob === job.id ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
                  </div>
                </button>

                {expandedJob === job.id && (
                  <div className="border-t border-gray-100 px-4 py-3 bg-gray-50 text-sm space-y-3">
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                      <Stat label="Emails scanned" value={job.emails_scanned} />
                      <Stat label="Timesheets found" value={job.emails_timesheet} color="text-green-600" />
                      <Stat label="Skipped" value={job.emails_skipped} />
                      <Stat label="Files saved" value={job.attachments_saved} color="text-blue-600" />
                    </div>

                    {job.status === 'AWAITING_APPROVAL' && (
                      <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 flex items-center justify-between">
                        <div>
                          <p className="text-sm font-semibold text-amber-800">Ready for your review</p>
                          <p className="text-xs text-amber-600">
                            {job.pending_approval_count} email{job.pending_approval_count !== 1 ? 's' : ''} with attachments found — confirm which to process
                          </p>
                        </div>
                        <button
                          onClick={() => setReviewJob(job.id)}
                          className="flex items-center gap-2 bg-amber-600 text-white text-xs font-medium px-3 py-1.5 rounded-lg hover:bg-amber-700 transition-colors"
                        >
                          Review & Confirm →
                        </button>
                      </div>
                    )}

                    {job.batch_id && (
                      <div className="flex items-center gap-2">
                        <span className="text-xs text-gray-500">Batch created:</span>
                        <button
                          onClick={() => router.push(`/batches/${job.batch_id}`)}
                          className="text-xs text-blue-600 underline"
                        >
                          View batch →
                        </button>
                      </div>
                    )}
                    {job.error_message && (
                      <div className="bg-red-50 border border-red-200 rounded p-2 text-xs text-red-700">
                        {job.error_message}
                      </div>
                    )}
                    {job.status === 'FAILED' && (
                      <button
                        onClick={() => retryMutation.mutate(job.id)}
                        disabled={retryMutation.isPending}
                        className="flex items-center gap-1.5 text-xs bg-orange-50 border border-orange-300 text-orange-700 px-3 py-1.5 rounded-lg hover:bg-orange-100 transition-colors"
                      >
                        <RefreshCw className="w-3 h-3" /> Retry
                      </button>
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

// ── Review Modal ──────────────────────────────────────────────────────────────

interface EmailMsg {
  id: string
  subject: string | null
  sender_name: string | null
  sender_email: string | null
  received_at: string | null
  body_snippet: string | null
  is_timesheet: boolean | null
  classification_reason: string | null
  classification_confidence: number | null
  has_attachments: boolean
  attachments_metadata: any[] | null
  processing_status: string
}

function ReviewModal({
  jobId,
  onClose,
  onApproved,
}: {
  jobId: string
  onClose: () => void
  onApproved: (batchId: string) => void
}) {
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [submitting, setSubmitting] = useState(false)

  const { data: messages = [], isLoading } = useQuery<EmailMsg[]>({
    queryKey: ['email-messages', jobId],
    queryFn: async () =>
      (await axios.get(`${BASE}/email/crawl-jobs/${jobId}/messages`, {
        params: { status: 'PENDING_APPROVAL' },
      })).data,
  })

  // Pre-select all on load
  useState(() => {
    if (messages.length > 0) {
      setSelected(new Set(messages.map(m => m.id)))
    }
  })

  const toggleAll = () => {
    if (selected.size === messages.length) setSelected(new Set())
    else setSelected(new Set(messages.map(m => m.id)))
  }

  const toggle = (id: string) => {
    setSelected(prev => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })
  }

  const approve = async () => {
    if (selected.size === 0) return
    setSubmitting(true)
    try {
      const res = await axios.post(`${BASE}/email/crawl-jobs/${jobId}/approve`, {
        message_ids: Array.from(selected),
      })
      onApproved(res.data.batch_id)
    } catch (err: any) {
      alert(err.response?.data?.detail || 'Failed to start processing')
      setSubmitting(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-3xl max-h-[85vh] flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200">
          <div>
            <h2 className="text-lg font-bold text-gray-900">Review Timesheet Emails</h2>
            <p className="text-xs text-gray-500 mt-0.5">
              Select the emails you want to process. Attachments will be extracted and a batch will be created.
            </p>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xl leading-none">✕</button>
        </div>

        {/* Body */}
        <div className="overflow-y-auto flex-1 px-6 py-4">
          {isLoading ? (
            <div className="flex items-center gap-2 text-gray-500 py-8 justify-center">
              <Loader2 className="w-5 h-5 animate-spin" /> Loading emails…
            </div>
          ) : messages.length === 0 ? (
            <div className="text-center text-gray-400 py-8">No emails pending review</div>
          ) : (
            <div className="space-y-3">
              {/* Select all */}
              <div className="flex items-center gap-2 pb-2 border-b border-gray-100">
                <input
                  type="checkbox"
                  checked={selected.size === messages.length && messages.length > 0}
                  onChange={toggleAll}
                  className="w-4 h-4 rounded accent-blue-600"
                />
                <span className="text-sm text-gray-600 font-medium">
                  Select all ({messages.length})
                </span>
                <span className="ml-auto text-xs text-gray-400">
                  {selected.size} selected
                </span>
              </div>

              {messages.map(msg => (
                <div
                  key={msg.id}
                  onClick={() => toggle(msg.id)}
                  className={`flex gap-3 p-3 rounded-xl border cursor-pointer transition-all ${
                    selected.has(msg.id)
                      ? 'border-blue-300 bg-blue-50'
                      : 'border-gray-200 bg-white hover:bg-gray-50'
                  }`}
                >
                  <input
                    type="checkbox"
                    checked={selected.has(msg.id)}
                    onChange={() => toggle(msg.id)}
                    onClick={e => e.stopPropagation()}
                    className="w-4 h-4 mt-1 rounded accent-blue-600 flex-shrink-0"
                  />
                  <div className="flex-1 min-w-0">
                    <div className="flex items-start justify-between gap-2">
                      <div>
                        <p className="text-sm font-semibold text-gray-800 truncate">
                          {msg.subject || '(no subject)'}
                        </p>
                        <p className="text-xs text-gray-500">
                          From: <span className="font-medium">{msg.sender_name || msg.sender_email}</span>
                          {msg.sender_name && msg.sender_email && ` <${msg.sender_email}>`}
                          {msg.received_at && ` · ${new Date(msg.received_at).toLocaleDateString()}`}
                        </p>
                      </div>
                      {msg.classification_confidence != null && (
                        <span className={`text-xs px-2 py-0.5 rounded-full flex-shrink-0 font-medium ${
                          msg.classification_confidence >= 0.8
                            ? 'bg-green-100 text-green-700'
                            : 'bg-yellow-100 text-yellow-700'
                        }`}>
                          {Math.round(msg.classification_confidence * 100)}% match
                        </span>
                      )}
                    </div>

                    {msg.body_snippet && (
                      <p className="text-xs text-gray-400 mt-1 truncate">{msg.body_snippet}</p>
                    )}

                    {/* Attachments list */}
                    {msg.attachments_metadata && msg.attachments_metadata.length > 0 && (
                      <div className="mt-2 flex flex-wrap gap-1.5">
                        {msg.attachments_metadata.map((att: any, i: number) => (
                          <span
                            key={i}
                            className="inline-flex items-center gap-1 bg-gray-100 text-gray-600 text-xs px-2 py-0.5 rounded-full"
                          >
                            📎 {att.name}
                          </span>
                        ))}
                      </div>
                    )}

                    {msg.classification_reason && (
                      <p className="text-xs text-gray-400 mt-1 italic">{msg.classification_reason}</p>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between px-6 py-4 border-t border-gray-200 bg-gray-50 rounded-b-2xl">
          <p className="text-xs text-gray-500">
            {selected.size} of {messages.length} email{messages.length !== 1 ? 's' : ''} selected
            {selected.size > 0 && ` · attachments will be extracted and processed`}
          </p>
          <div className="flex gap-3">
            <button
              onClick={onClose}
              className="px-4 py-2 text-sm text-gray-600 bg-white border border-gray-300 rounded-lg hover:bg-gray-50 transition-colors"
            >
              Cancel
            </button>
            <button
              disabled={selected.size === 0 || submitting}
              onClick={approve}
              className="flex items-center gap-2 px-5 py-2 text-sm font-medium text-white bg-green-600 rounded-lg hover:bg-green-700 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
            >
              {submitting ? <Loader2 className="w-4 h-4 animate-spin" /> : <CheckCircle2 className="w-4 h-4" />}
              Confirm & Process {selected.size > 0 && `(${selected.size})`}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

function StatusBadge({ status }: { status: string }) {
  const styles: Record<string, string> = {
    PENDING:            'bg-gray-100 text-gray-600',
    RUNNING:            'bg-blue-100 text-blue-700',
    AWAITING_APPROVAL:  'bg-amber-100 text-amber-700',
    COMPLETED:          'bg-green-100 text-green-700',
    FAILED:             'bg-red-100 text-red-700',
  }
  const icons: Record<string, React.ReactNode> = {
    PENDING:            <Clock className="w-3 h-3" />,
    RUNNING:            <Loader2 className="w-3 h-3 animate-spin" />,
    AWAITING_APPROVAL:  <Mail className="w-3 h-3" />,
    COMPLETED:          <CheckCircle2 className="w-3 h-3" />,
    FAILED:             <XCircle className="w-3 h-3" />,
  }
  const labels: Record<string, string> = {
    AWAITING_APPROVAL: 'Needs Review',
  }
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium ${styles[status] || styles.PENDING}`}>
      {icons[status]} {labels[status] || status}
    </span>
  )
}

function Stat({ label, value, color = 'text-gray-800' }: { label: string; value: number; color?: string }) {
  return (
    <div className="bg-white rounded-lg px-3 py-2 border border-gray-100 text-center">
      <p className={`text-lg font-bold ${color}`}>{value}</p>
      <p className="text-xs text-gray-500">{label}</p>
    </div>
  )
}
