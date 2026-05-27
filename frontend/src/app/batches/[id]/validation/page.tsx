'use client'
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { listValidation, resolveValidationError, previewFileUrl, listFiles, listEmployees } from '@/lib/api'
import SeverityBadge from '@/components/ui/SeverityBadge'
import StatusBadge from '@/components/ui/StatusBadge'
import {
  AlertTriangle, CheckCircle2, Eye, FileText,
  X, ExternalLink, UserCheck, ClipboardEdit, Loader2, ShieldAlert,
} from 'lucide-react'
import Link from 'next/link'

interface Props { params: { id: string } }

const SEVERITY_ORDER = ['BLOCKER', 'ERROR', 'WARNING', 'INFO']

// These rules are global / admin-level — excluded from per-batch HR view
const ADMIN_ONLY_RULES = new Set(['TWO_MONTH_INACTIVE'])

interface IssueDrawerProps {
  issue: {
    id: string
    rule_code: string
    severity: string
    message: string
    expected_value?: string
    actual_value?: string
    action_required?: string
    file_id?: string
    entry_id?: string
    employee_id?: string
    status: string
  }
  batchId: string
  onClose: () => void
  onResolved: () => void
}

function IssueDrawer({ issue, batchId, onClose, onResolved }: IssueDrawerProps) {
  const qc = useQueryClient()
  const [note, setNote] = useState('')
  const [reviewerName, setReviewerName] = useState('')
  const [employeeName, setEmployeeName] = useState('')
  const [selectedEmployeeId, setSelectedEmployeeId] = useState('')
  const [hours, setHours] = useState('')
  const [workDate, setWorkDate] = useState('')
  const [showPreview, setShowPreview] = useState(false)

  // Load the file record to get name and extension
  const { data: filesData } = useQuery({
    queryKey: ['files', batchId],
    queryFn: () => listFiles(batchId, { limit: 200 }),
    enabled: !!issue.file_id,
  })
  const fileRecord = filesData?.items?.find((f: { id: string }) => f.id === issue.file_id)

  // Load employees for dropdown picker
  const { data: employeesData } = useQuery({
    queryKey: ['employees'],
    queryFn: listEmployees,
  })
  const employees = employeesData?.items ?? []

  const resolveMut = useMutation({
    mutationFn: () => resolveValidationError(
      issue.id,
      note || undefined,
      {
        employee_name: employeeName || undefined,
        employee_id: selectedEmployeeId || undefined,
        hours: hours ? parseFloat(hours) : undefined,
        date: workDate || undefined,
      },
      reviewerName || undefined,
    ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['validation', batchId] })
      qc.invalidateQueries({ queryKey: ['files', batchId] })
      onResolved()
      onClose()
    },
  })

  const needsEmployeeFix = ['NO_EMPLOYEE_MATCH', 'UNMATCHED_FILE', 'MISSING_EMPLOYEE',
    'EMPLOYEE_NOT_MATCHED', 'NOT_MATCHED'].some(c => issue.rule_code.includes(c))
  const needsHoursFix = ['HOURS', 'OVERTIME', 'DAILY_HOURS'].some(c =>
    issue.rule_code.includes(c)
  )
  const needsDateFix = ['DATE', 'PERIOD', 'MISSING_DATES'].some(c =>
    issue.rule_code.includes(c)
  )

  return (
    <div className="fixed inset-0 z-50 flex">
      {/* Backdrop */}
      <div className="flex-1 bg-black/40" onClick={onClose} />

      {/* Drawer panel */}
      <div className="w-[540px] bg-white h-full overflow-y-auto flex flex-col shadow-2xl">
        {/* Header */}
        <div className={`px-6 py-4 flex items-center justify-between border-b ${
          issue.severity === 'BLOCKER' || issue.severity === 'ERROR'
            ? 'bg-red-50 border-red-200'
            : issue.severity === 'WARNING'
            ? 'bg-yellow-50 border-yellow-200'
            : 'bg-blue-50 border-blue-200'
        }`}>
          <div className="flex items-center gap-3">
            <SeverityBadge severity={issue.severity} />
            <span className="font-semibold text-gray-900 text-sm">{issue.rule_code}</span>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-700">
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="flex-1 px-6 py-5 space-y-5">
          {/* Issue description */}
          <div className="bg-gray-50 rounded-xl p-4 space-y-2.5 text-sm">
            <p className="text-gray-900 font-medium">{issue.message}</p>
            {issue.expected_value && (
              <div className="flex gap-2 text-xs">
                <span className="text-gray-500 shrink-0">Expected:</span>
                <span className="text-green-700 font-mono">{issue.expected_value}</span>
              </div>
            )}
            {issue.actual_value && (
              <div className="flex gap-2 text-xs">
                <span className="text-gray-500 shrink-0">Actual:</span>
                <span className="text-red-700 font-mono">{issue.actual_value}</span>
              </div>
            )}
            {issue.action_required && !issue.action_required.startsWith('[RESOLVED') && (
              <div className="flex gap-2 text-xs">
                <span className="text-orange-600 shrink-0 font-medium">Action:</span>
                <span className="text-orange-800">{issue.action_required}</span>
              </div>
            )}
          </div>

          {/* File preview */}
          {issue.file_id && (
            <div className="border border-gray-200 rounded-xl overflow-hidden">
              <div className="flex items-center justify-between px-4 py-2.5 bg-gray-50 border-b border-gray-200">
                <div className="flex items-center gap-2 text-sm font-medium text-gray-700">
                  <FileText className="w-4 h-4 text-blue-500" />
                  {fileRecord ? fileRecord.file_name : 'Source File'}
                </div>
                <div className="flex gap-2">
                  <button
                    onClick={() => setShowPreview(!showPreview)}
                    className="text-xs text-blue-600 hover:text-blue-800 flex items-center gap-1 font-medium"
                  >
                    <Eye className="w-3.5 h-3.5" />
                    {showPreview ? 'Hide' : 'Preview'}
                  </button>
                  <a
                    href={previewFileUrl(issue.file_id)}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-xs text-gray-500 hover:text-gray-700 flex items-center gap-1"
                  >
                    <ExternalLink className="w-3.5 h-3.5" />
                    Open
                  </a>
                </div>
              </div>
              {showPreview && (
                <div className="bg-gray-100 h-64 flex items-center justify-center">
                  {(fileRecord?.file_ext === '.pdf' || ['.png', '.jpg', '.jpeg'].includes(fileRecord?.file_ext ?? '')) ? (
                    <iframe
                      src={previewFileUrl(issue.file_id)}
                      className="w-full h-64 border-0"
                      title="File preview"
                    />
                  ) : (
                    <div className="text-center text-gray-500 text-sm p-4">
                      <FileText className="w-8 h-8 mx-auto mb-2 text-gray-400" />
                      <p>Preview not available for this file type.</p>
                      <a
                        href={previewFileUrl(issue.file_id)}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-blue-600 underline text-xs mt-1 inline-block"
                      >
                        Download to view
                      </a>
                    </div>
                  )}
                </div>
              )}
            </div>
          )}

          {/* Human correction form */}
          <div className="space-y-4">
            <div className="flex items-center gap-2 text-sm font-semibold text-gray-700">
              <ClipboardEdit className="w-4 h-4 text-indigo-500" />
              Manual Correction
              <span className="text-xs font-normal text-gray-400">(fill in what's missing or wrong)</span>
            </div>

            {needsEmployeeFix && (
              <div className="space-y-3">
                {/* Employee dropdown picker */}
                {employees.length > 0 && (
                  <div>
                    <label className="block text-xs font-medium text-gray-600 mb-1">
                      Select Employee from Records
                    </label>
                    <select
                      value={selectedEmployeeId}
                      onChange={(e) => {
                        setSelectedEmployeeId(e.target.value)
                        const emp = employees.find((emp: { id: string; full_name: string }) => emp.id === e.target.value)
                        if (emp) setEmployeeName(emp.full_name)
                      }}
                      className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-400 focus:border-indigo-400"
                    >
                      <option value="">— pick an employee —</option>
                      {employees.map((emp: { id: string; full_name: string }) => (
                        <option key={emp.id} value={emp.id}>{emp.full_name}</option>
                      ))}
                    </select>
                  </div>
                )}
                <div>
                  <label className="block text-xs font-medium text-gray-600 mb-1">
                    Or type Correct Employee Name
                  </label>
                  <input
                    type="text"
                    value={employeeName}
                    onChange={(e) => { setEmployeeName(e.target.value); setSelectedEmployeeId('') }}
                    placeholder="Full name as it appears in records"
                    className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-400 focus:border-indigo-400"
                  />
                </div>
              </div>
            )}

            {needsHoursFix && (
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">
                  Correct Hours
                </label>
                <input
                  type="number"
                  value={hours}
                  onChange={(e) => setHours(e.target.value)}
                  placeholder="e.g. 8.0"
                  step="0.5"
                  min="0"
                  max="24"
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-400"
                />
              </div>
            )}

            {needsDateFix && (
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">
                  Correct Date
                </label>
                <input
                  type="date"
                  value={workDate}
                  onChange={(e) => setWorkDate(e.target.value)}
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-400"
                />
              </div>
            )}

            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">
                Resolution Note
                <span className="text-gray-400 font-normal ml-1">(explain what you did)</span>
              </label>
              <textarea
                value={note}
                onChange={(e) => setNote(e.target.value)}
                rows={2}
                placeholder="e.g. Confirmed with employee — hours were 8h not 0h"
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm resize-none focus:ring-2 focus:ring-indigo-400"
              />
            </div>

            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">
                Your Name
                <span className="text-gray-400 font-normal ml-1">(for audit trail)</span>
              </label>
              <input
                type="text"
                value={reviewerName}
                onChange={(e) => setReviewerName(e.target.value)}
                placeholder="e.g. Priya HR"
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-400"
              />
            </div>
          </div>
        </div>

        {/* Footer actions */}
        <div className="border-t border-gray-200 px-6 py-4 flex items-center justify-between bg-white">
          <button
            onClick={onClose}
            className="text-sm text-gray-500 hover:text-gray-700"
          >
            Cancel
          </button>
          <button
            onClick={() => resolveMut.mutate()}
            disabled={resolveMut.isPending}
            className="flex items-center gap-2 bg-green-600 hover:bg-green-700 text-white text-sm font-medium px-5 py-2 rounded-lg transition-colors disabled:opacity-50"
          >
            {resolveMut.isPending ? (
              <><Loader2 className="w-4 h-4 animate-spin" /> Saving…</>
            ) : (
              <><UserCheck className="w-4 h-4" /> Mark Resolved</>
            )}
          </button>
        </div>
      </div>
    </div>
  )
}

export default function ValidationPage({ params }: Props) {
  const { id: batchId } = params
  const qc = useQueryClient()
  const [severityFilter, setSeverityFilter] = useState('')
  const [statusFilter, setStatusFilter] = useState('OPEN')
  const [activeIssue, setActiveIssue] = useState<{
    id: string; rule_code: string; severity: string; message: string;
    expected_value?: string; actual_value?: string; action_required?: string;
    file_id?: string; entry_id?: string; employee_id?: string; status: string;
  } | null>(null)

  const { data, isLoading } = useQuery({
    queryKey: ['validation', batchId, severityFilter, statusFilter],
    queryFn: () => listValidation(batchId, {
      severity: severityFilter || undefined,
      status: statusFilter || undefined,
      limit: 200,
    }),
  })

  // Check if there are any admin-only rules in the data (not shown here)
  const hasAdminOnlyIssues = data?.items?.some((e) => ADMIN_ONLY_RULES.has(e.rule_code))
  // Filter admin-only rules from the per-batch table
  const visibleItems = data?.items?.filter((e) => !ADMIN_ONLY_RULES.has(e.rule_code)) ?? []

  return (
    <div className="p-6 max-w-7xl mx-auto">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <AlertTriangle className="w-5 h-5 text-yellow-500" />
          <h2 className="text-lg font-semibold text-gray-900">Validation Issues</h2>
          <span className="text-xs text-gray-400 font-normal">— click a row to review &amp; fix</span>
        </div>

        {data && (
          <div className="flex items-center gap-4 text-sm">
            {data.blocker_count > 0 && <span className="text-red-600 font-semibold">{data.blocker_count} Blockers</span>}
            {data.error_count > 0 && <span className="text-red-500">{data.error_count} Errors</span>}
            {data.warning_count > 0 && <span className="text-yellow-600">{data.warning_count} Warnings</span>}
            {data.info_count > 0 && <span className="text-blue-500">{data.info_count} Info</span>}
          </div>
        )}
      </div>

      {/* Admin-only rules notice */}
      {hasAdminOnlyIssues && (
        <div className="flex items-start gap-3 bg-amber-50 border border-amber-200 rounded-xl px-4 py-3 mb-4 text-sm">
          <ShieldAlert className="w-4 h-4 text-amber-600 mt-0.5 shrink-0" />
          <div className="flex-1">
            <p className="text-amber-800 font-medium">Inactive employee warnings detected</p>
            <p className="text-amber-700 text-xs mt-0.5">
              <code className="font-mono bg-amber-100 px-1 rounded">TWO_MONTH_INACTIVE</code> warnings are organisation-level and only shown in the{' '}
              <Link href="/admin" className="underline font-medium">Admin → Inactive Report</Link> tab,
              not here per batch.
            </p>
          </div>
        </div>
      )}

      {/* Filters */}
      <div className="flex gap-3 mb-4">
        <select value={severityFilter} onChange={(e) => setSeverityFilter(e.target.value)}
          className="border border-gray-200 rounded-lg px-3 py-2 text-sm">
          <option value="">All Severities</option>
          {SEVERITY_ORDER.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
        <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}
          className="border border-gray-200 rounded-lg px-3 py-2 text-sm">
          <option value="OPEN">Open</option>
          <option value="RESOLVED">Resolved</option>
          <option value="">All</option>
        </select>
      </div>

      {isLoading ? (
        <div className="text-center py-12 text-gray-400">Loading...</div>
      ) : visibleItems.length === 0 ? (
        <div className="bg-green-50 rounded-xl border border-green-200 p-12 text-center">
          <CheckCircle2 className="w-10 h-10 text-green-500 mx-auto mb-3" />
          <p className="text-green-700 font-medium">No validation issues found!</p>
        </div>
      ) : (
        <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b border-gray-200">
              <tr>
                {['Severity', 'Rule', 'Message', 'Expected', 'Actual', 'Action', 'Status', ''].map((h) => (
                  <th key={h} className="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase tracking-wider whitespace-nowrap">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {visibleItems.map((e) => (
                <tr
                  key={e.id}
                  onClick={() => e.status === 'OPEN' && setActiveIssue(e as any)}
                  className={`transition-colors ${e.status === 'OPEN' ? 'cursor-pointer hover:bg-indigo-50' : ''} ${
                    e.severity === 'BLOCKER' || e.severity === 'ERROR' ? 'bg-red-50 hover:bg-red-100' :
                    e.severity === 'WARNING' ? 'bg-yellow-50 hover:bg-yellow-100' : ''
                  }`}
                >
                  <td className="px-4 py-3"><SeverityBadge severity={e.severity} /></td>
                  <td className="px-4 py-3 font-mono text-xs text-gray-700">{e.rule_code}</td>
                  <td className="px-4 py-3 text-gray-800 max-w-[220px]">{e.message}</td>
                  <td className="px-4 py-3 text-gray-500 text-xs">{e.expected_value || '—'}</td>
                  <td className="px-4 py-3 text-gray-500 text-xs">{e.actual_value || '—'}</td>
                  <td className="px-4 py-3 text-orange-700 text-xs max-w-[160px]">{e.action_required || '—'}</td>
                  <td className="px-4 py-3"><StatusBadge status={e.status} /></td>
                  <td className="px-4 py-3">
                    {e.status === 'OPEN' ? (
                      <div className="flex items-center gap-2">
                        {e.file_id && (
                          <a
                            href={previewFileUrl(e.file_id)}
                            target="_blank"
                            rel="noopener noreferrer"
                            onClick={(ev) => ev.stopPropagation()}
                            title="Open file"
                            className="p-1 rounded hover:bg-blue-100 text-blue-500 transition-colors"
                          >
                            <ExternalLink className="w-3.5 h-3.5" />
                          </a>
                        )}
                        <button
                          onClick={(ev) => { ev.stopPropagation(); setActiveIssue(e as any) }}
                          className="flex items-center gap-1 text-xs bg-indigo-50 hover:bg-indigo-100 text-indigo-700 px-2 py-1 rounded-lg font-medium transition-colors"
                        >
                          <ClipboardEdit className="w-3 h-3" />
                          Review &amp; Fix
                        </button>
                      </div>
                    ) : (
                      <CheckCircle2 className="w-4 h-4 text-green-500" />
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Human-in-the-loop drawer */}
      {activeIssue && (
        <IssueDrawer
          issue={activeIssue}
          batchId={batchId}
          onClose={() => setActiveIssue(null)}
          onResolved={() => setActiveIssue(null)}
        />
      )}
    </div>
  )
}
