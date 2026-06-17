'use client'
import { useMemo, useState } from 'react'

export interface DayEntry {
  date: string            // YYYY-MM-DD
  hours: number
  entry_type?: string | null
  leave_type?: string | null
  in_time?: string | null
  out_time?: string | null
  break_minutes?: number | null
  regular_hours?: number | null
  overtime_hours?: number | null
}

const WD = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December']

function ymd(s: string): [number, number, number] {
  const [y, m, d] = s.split('-').map(Number); return [y, m, d]
}

// type → cell colors (bg / text / dot)
function typeStyle(e?: DayEntry, inMonth = true): { bg: string; text: string; label: string } {
  if (!inMonth) return { bg: 'bg-transparent', text: 'text-transparent', label: '' }
  if (!e) return { bg: 'bg-gray-50', text: 'text-gray-300', label: '' }
  const t = (e.entry_type || 'WORK').toUpperCase()
  if ((e.overtime_hours || 0) > 0) return { bg: 'bg-amber-50 border-amber-200', text: 'text-amber-700', label: 'OT' }
  if (t === 'LEAVE' || e.leave_type) return { bg: 'bg-purple-50 border-purple-200', text: 'text-purple-700', label: e.leave_type || 'Leave' }
  if (t === 'HOLIDAY') return { bg: 'bg-teal-50 border-teal-200', text: 'text-teal-700', label: 'Holiday' }
  if (t === 'ABSENT') return { bg: 'bg-rose-50 border-rose-200', text: 'text-rose-700', label: 'Absent' }
  if (t === 'WEEKEND' || (e.hours || 0) === 0) return { bg: 'bg-gray-50 border-gray-100', text: 'text-gray-400', label: '' }
  return { bg: 'bg-indigo-50 border-indigo-200', text: 'text-indigo-700', label: 'Work' }
}

export default function MonthCalendar({ entries, name, subtitle, totalHours }:
  { entries: DayEntry[]; name?: string; subtitle?: string; totalHours?: number }) {

  const byDate = useMemo(() => {
    const m = new Map<string, DayEntry>()
    for (const e of entries) if (e.date) m.set(e.date, e)
    return m
  }, [entries])

  // months present in the data, sorted
  const months = useMemo(() => {
    const set = new Set<string>()
    for (const e of entries) if (e.date) { const [y, mo] = ymd(e.date); set.add(`${y}-${mo}`) }
    return Array.from(set).sort()
  }, [entries])

  const [idx, setIdx] = useState(0)
  const cur = months[idx] || (() => { const d = new Date(); return `${d.getFullYear()}-${d.getMonth() + 1}` })()
  const [cy, cm] = cur.split('-').map(Number)   // cm is 1-based
  const [selected, setSelected] = useState<string | null>(null)

  const firstDow = new Date(cy, cm - 1, 1).getDay()
  const daysInMonth = new Date(cy, cm, 0).getDate()

  // monthly total for the visible month
  const monthTotal = useMemo(() => {
    let t = 0
    for (const e of entries) {
      if (!e.date) continue
      const [y, mo] = ymd(e.date)
      if (y === cy && mo === cm) t += e.hours || 0
    }
    return Math.round(t * 100) / 100
  }, [entries, cy, cm])

  const cells: Array<{ day: number | null; key: string }> = []
  for (let i = 0; i < firstDow; i++) cells.push({ day: null, key: `b${i}` })
  for (let d = 1; d <= daysInMonth; d++) cells.push({ day: d, key: `d${d}` })

  const sel = selected ? byDate.get(selected) : null

  return (
    <div className="bg-white border border-gray-200 rounded-2xl overflow-hidden">
      <div className="flex items-center justify-between px-4 py-3 border-b border-gray-100 bg-gray-50">
        <div className="min-w-0">
          {name && <div className="text-sm font-semibold text-gray-800 truncate">{name}</div>}
          <div className="text-xs text-gray-500">{subtitle || `${MONTHS[cm - 1]} ${cy}`}</div>
        </div>
        <div className="flex items-center gap-3">
          <div className="text-right">
            <div className="text-xs text-gray-400">Month total</div>
            <div className="text-lg font-bold text-indigo-600">{monthTotal}h</div>
          </div>
          {months.length > 1 && (
            <div className="flex items-center gap-1">
              <button onClick={() => { setIdx(Math.max(0, idx - 1)); setSelected(null) }}
                disabled={idx === 0}
                className="px-2 py-1 rounded-lg border border-gray-200 text-gray-600 disabled:opacity-30 hover:bg-gray-100">‹</button>
              <button onClick={() => { setIdx(Math.min(months.length - 1, idx + 1)); setSelected(null) }}
                disabled={idx >= months.length - 1}
                className="px-2 py-1 rounded-lg border border-gray-200 text-gray-600 disabled:opacity-30 hover:bg-gray-100">›</button>
            </div>
          )}
        </div>
      </div>

      <div className="p-3">
        <div className="grid grid-cols-7 gap-1 mb-1">
          {WD.map(w => <div key={w} className="text-[11px] font-medium text-gray-400 text-center py-1">{w}</div>)}
        </div>
        <div className="grid grid-cols-7 gap-1">
          {cells.map(c => {
            if (c.day === null) return <div key={c.key} className="aspect-square" />
            const dstr = `${cy}-${String(cm).padStart(2, '0')}-${String(c.day).padStart(2, '0')}`
            const e = byDate.get(dstr)
            const st = typeStyle(e, true)
            const isSel = selected === dstr
            return (
              <button key={c.key}
                onClick={() => setSelected(isSel ? null : dstr)}
                className={`aspect-square rounded-lg border ${st.bg} ${isSel ? 'ring-2 ring-indigo-500' : ''}
                  flex flex-col items-center justify-center p-1 transition hover:brightness-95 text-center`}>
                <span className="text-[10px] text-gray-400 self-start leading-none">{c.day}</span>
                {e ? (
                  <>
                    <span className={`text-sm font-bold ${st.text} leading-tight`}>{e.hours || 0}</span>
                    {st.label && <span className={`text-[9px] ${st.text} leading-none`}>{st.label}</span>}
                  </>
                ) : <span className="text-[11px] text-gray-200">·</span>}
              </button>
            )
          })}
        </div>
      </div>

      {/* legend */}
      <div className="flex flex-wrap gap-3 px-4 py-2 border-t border-gray-100 text-[11px] text-gray-500">
        <Legend cls="bg-indigo-200" label="Work" />
        <Legend cls="bg-amber-200" label="Overtime" />
        <Legend cls="bg-purple-200" label="Leave" />
        <Legend cls="bg-teal-200" label="Holiday" />
        <Legend cls="bg-rose-200" label="Absent" />
        <Legend cls="bg-gray-100" label="Off / 0h" />
      </div>

      {/* day detail */}
      {sel && (
        <div className="px-4 py-3 border-t border-indigo-100 bg-indigo-50/50 text-sm">
          <div className="font-semibold text-gray-800 mb-1">{selected}</div>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs text-gray-600">
            <Field k="Hours" v={`${sel.hours ?? 0}h`} />
            <Field k="Regular" v={`${sel.regular_hours ?? 0}h`} />
            <Field k="Overtime" v={`${sel.overtime_hours ?? 0}h`} />
            <Field k="Type" v={sel.leave_type || sel.entry_type || 'WORK'} />
            <Field k="In" v={sel.in_time || '—'} />
            <Field k="Out" v={sel.out_time || '—'} />
            <Field k="Break" v={sel.break_minutes != null ? `${sel.break_minutes}m` : '—'} />
          </div>
        </div>
      )}
    </div>
  )
}

function Legend({ cls, label }: { cls: string; label: string }) {
  return <span className="inline-flex items-center gap-1"><span className={`w-3 h-3 rounded ${cls} inline-block`} />{label}</span>
}
function Field({ k, v }: { k: string; v: string }) {
  return <div><span className="text-gray-400">{k}: </span><span className="font-medium text-gray-700">{v}</span></div>
}
