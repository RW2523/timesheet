'use client'
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { listEmployees, listVendors, listPayrollPeriods } from '@/lib/api'
import { Settings, Users, Building2, Calendar, DollarSign, Plus } from 'lucide-react'
import axios from 'axios'

const BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api/v1'

type Tab = 'employees' | 'vendors' | 'periods'

export default function AdminPage() {
  const [tab, setTab] = useState<Tab>('employees')

  const tabs: { key: Tab; label: string; icon: React.ReactNode }[] = [
    { key: 'employees', label: 'Employees', icon: <Users className="w-4 h-4" /> },
    { key: 'vendors', label: 'Vendors', icon: <Building2 className="w-4 h-4" /> },
    { key: 'periods', label: 'Payroll Periods', icon: <Calendar className="w-4 h-4" /> },
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
      <div className="flex border-b border-gray-200 mb-6">
        {tabs.map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={`flex items-center gap-2 px-5 py-3 text-sm font-medium border-b-2 transition-colors ${
              tab === t.key
                ? 'border-blue-500 text-blue-600'
                : 'border-transparent text-gray-500 hover:text-gray-700'
            }`}
          >
            {t.icon} {t.label}
          </button>
        ))}
      </div>

      {tab === 'employees' && <EmployeesTab />}
      {tab === 'vendors' && <VendorsTab />}
      {tab === 'periods' && <PeriodsTab />}
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
