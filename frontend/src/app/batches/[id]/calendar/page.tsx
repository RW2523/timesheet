'use client'
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import Link from 'next/link'
import { listTimesheets, TimesheetCal } from '@/lib/api'
import MonthCalendar from '@/components/MonthCalendar'
import { ArrowLeft, UserCheck, UserX, Loader2 } from 'lucide-react'

interface Props { params: { id: string } }

export default function CalendarPage({ params }: Props) {
  const { id } = params
  const { data, isLoading, isError } = useQuery({
    queryKey: ['timesheets', id],
    queryFn: () => listTimesheets(id),
  })
  const [active, setActive] = useState(0)
  const sheets: TimesheetCal[] = data?.timesheets || []
  const missing = data?.missing_files || []
  const totalHours = sheets.reduce((a, s) => a + (s.total_hours || 0), 0)

  return (
    <div className="max-w-6xl mx-auto p-6 space-y-5">
      <div className="flex items-center gap-3">
        <Link href={`/batches/${id}`} className="text-gray-500 hover:text-gray-700"><ArrowLeft className="w-5 h-5" /></Link>
        <div>
          <h1 className="text-xl font-bold text-gray-800">Calendar preview</h1>
          <p className="text-sm text-gray-500">Hours worked per day, by timesheet.</p>
        </div>
      </div>

      {isLoading && (
        <div className="flex items-center gap-2 text-gray-500 py-16 justify-center">
          <Loader2 className="w-5 h-5 animate-spin" /> Loading timesheets…
        </div>
      )}
      {isError && <div className="text-red-600 py-10 text-center">Failed to load timesheets.</div>}
      {!isLoading && !isError && sheets.length === 0 && (
        <div className="text-gray-500 py-16 text-center">No timesheets extracted yet for this batch.</div>
      )}

      {/* simple summary */}
      {!isLoading && !isError && (sheets.length > 0 || missing.length > 0) && (
        <div className="flex flex-wrap gap-3">
          <Stat label="Timesheets extracted" value={`${sheets.length}`} tone="indigo" />
          <Stat label="Total hours" value={`${Math.round(totalHours)}h`} tone="indigo" />
          <Stat label="Not extracted" value={`${missing.length}`} tone={missing.length ? 'rose' : 'gray'} />
        </div>
      )}

      {/* what is missing — files that produced no timesheet */}
      {missing.length > 0 && (
        <div className="bg-rose-50 border border-rose-200 rounded-xl p-3">
          <div className="text-sm font-semibold text-rose-800 mb-1">Missing — {missing.length} file(s) had no timesheet extracted</div>
          <div className="flex flex-wrap gap-2">
            {missing.map(m => (
              <span key={m.file_id} className="text-xs bg-white border border-rose-200 text-rose-700 rounded-lg px-2 py-1">
                {m.file_name} <span className="text-rose-400">· {m.status}</span>
              </span>
            ))}
          </div>
        </div>
      )}

      {sheets.length > 0 && (
        <div className="grid grid-cols-1 md:grid-cols-[260px_1fr] gap-5">
          {/* timesheet picker */}
          <div className="space-y-1">
            {sheets.map((s, i) => (
              <button key={s.submission_id} onClick={() => setActive(i)}
                className={`w-full text-left px-3 py-2 rounded-xl border transition ${i === active
                  ? 'bg-indigo-50 border-indigo-300' : 'bg-white border-gray-200 hover:bg-gray-50'}`}>
                <div className="flex items-center justify-between gap-2">
                  <span className="text-sm font-medium text-gray-800 truncate">{s.employee_name}</span>
                  <span className="text-xs font-semibold text-indigo-600 whitespace-nowrap">{s.total_hours}h</span>
                </div>
                <div className="flex items-center gap-1 mt-0.5">
                  {s.matched
                    ? <span className="inline-flex items-center gap-1 text-[10px] text-emerald-600"><UserCheck className="w-3 h-3" />matched</span>
                    : <span className="inline-flex items-center gap-1 text-[10px] text-amber-600"><UserX className="w-3 h-3" />unmatched</span>}
                  <span className="text-[10px] text-gray-400 truncate">· {s.file_name}</span>
                </div>
              </button>
            ))}
          </div>

          {/* selected calendar */}
          <div>
            {sheets[active] && (
              <MonthCalendar
                key={sheets[active].submission_id}
                entries={sheets[active].entries}
                name={sheets[active].employee_name}
                periodStart={sheets[active].period_start}
                periodEnd={sheets[active].period_end}
                subtitle={`${sheets[active].entries.length} day(s) · ${sheets[active].total_hours}h total · ${sheets[active].matched ? 'employee matched' : 'employee not matched (extracted name)'}`}
              />
            )}
          </div>
        </div>
      )}
    </div>
  )
}

function Stat({ label, value, tone }: { label: string; value: string; tone: 'indigo' | 'rose' | 'gray' }) {
  const c = tone === 'rose' ? 'text-rose-600' : tone === 'gray' ? 'text-gray-500' : 'text-indigo-600'
  return (
    <div className="bg-white border border-gray-200 rounded-xl px-4 py-2">
      <div className="text-xs text-gray-400">{label}</div>
      <div className={`text-lg font-bold ${c}`}>{value}</div>
    </div>
  )
}
