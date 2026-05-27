import axios from 'axios'
import type {
  BatchSummary, DashboardStats, FileRecord, TimesheetEntry,
  ValidationError, ValidationListResponse, GeneratedReport,
  Employee, PayrollPeriod,
} from '@/types'

// Always use a relative path so the browser calls the same origin it loaded
// the page from. Next.js rewrites /api/v1/* → backend internally, which means
// this works identically on localhost, Tailscale, or any other hostname.
const BASE = '/api/v1'

const http = axios.create({ baseURL: BASE, timeout: 30000 })

// ── Health ────────────────────────────────────────────────────────────────────

export const healthCheck = () => http.get('/health')

// ── Dashboard ─────────────────────────────────────────────────────────────────

export const getDashboard = async (): Promise<DashboardStats> => {
  const { data } = await http.get('/dashboard')
  return data
}

// ── Batches ───────────────────────────────────────────────────────────────────

export const listBatches = async (params?: { skip?: number; limit?: number; status?: string }) => {
  const { data } = await http.get('/batches', { params })
  return data as { items: BatchSummary[]; total: number }
}

export const getBatch = async (batchId: string): Promise<BatchSummary> => {
  const { data } = await http.get(`/batches/${batchId}`)
  return data
}

export const cancelBatch = async (batchId: string) => {
  const { data } = await http.post(`/batches/${batchId}/cancel`)
  return data
}

export const deleteBatch = async (batchId: string) => {
  const { data } = await http.delete(`/batches/${batchId}`)
  return data
}
export const getBatchStatus = async (batchId: string) => {
  const { data } = await http.get(`/batches/${batchId}/status`)
  return data as {
    batch_id: string
    status: string
    total_files: number
    done_files: number
    failed_files: number
    review_files: number
    progress_pct: number
    current_file?: string
    current_stage?: string
  }
}

export const getBatchStats = async (batchId: string) => {
  const { data } = await http.get(`/batches/${batchId}/stats`)
  return data as {
    batch_id: string
    ocr_files: number
    matched_files: number
    unmatched_files: number
    extraction_failed: number
    non_timesheet: number
  }
}

// ── Upload ────────────────────────────────────────────────────────────────────

export const uploadZip = async (
  file: File,
  payrollPeriodId?: string,
  notes?: string,
  onProgress?: (pct: number) => void,
  periodType?: string,
  periodValue?: string,
) => {
  const form = new FormData()
  form.append('file', file)
  if (payrollPeriodId) form.append('payroll_period_id', payrollPeriodId)
  if (notes) form.append('notes', notes)
  form.append('period_type', periodType || 'month')
  if (periodValue) form.append('period_value', periodValue)

  const { data } = await http.post('/upload', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
    onUploadProgress: (e) => {
      if (onProgress && e.total) onProgress(Math.round((e.loaded / e.total) * 100))
    },
  })
  return data
}

// ── Files ─────────────────────────────────────────────────────────────────────

export const listFiles = async (batchId: string, params?: { skip?: number; limit?: number; status?: string }) => {
  const { data } = await http.get(`/batches/${batchId}/files`, { params })
  return data as { items: FileRecord[]; total: number }
}

export const getRawExtraction = async (fileId: string) => {
  const { data } = await http.get(`/files/${fileId}/raw-extraction`)
  return data
}

export const assignEmployee = async (fileId: string, employeeId: string, reason?: string) => {
  const { data } = await http.post(`/files/${fileId}/assign-employee`, {
    employee_id: employeeId,
    override_reason: reason,
  })
  return data
}

export const markNonTimesheet = async (fileId: string, reason?: string) => {
  const { data } = await http.post(`/files/${fileId}/mark-non-timesheet`, { reason })
  return data
}

export const reprocessFile = async (fileId: string) => {
  const { data } = await http.post(`/files/${fileId}/reprocess`)
  return data
}

export const getEmployeeMatches = async (batchId: string) => {
  const { data } = await http.get(`/batches/${batchId}/employee-matches`)
  return data as { items: FileRecord[]; total: number }
}

// ── Entries ───────────────────────────────────────────────────────────────────

export const listEntries = async (batchId: string, params?: { skip?: number; limit?: number; employee_id?: string }) => {
  const { data } = await http.get(`/batches/${batchId}/entries`, { params })
  return data as { items: TimesheetEntry[]; total: number }
}

// ── Validation ────────────────────────────────────────────────────────────────

export const listValidation = async (
  batchId: string,
  params?: { severity?: string; status?: string; skip?: number; limit?: number },
): Promise<ValidationListResponse> => {
  const { data } = await http.get(`/batches/${batchId}/validation`, { params })
  return data
}

export const resolveValidationError = async (
  errorId: string,
  note?: string,
  correction?: {
    employee_name?: string
    employee_id?: string
    hours?: number
    date?: string
    notes?: string
  },
  resolvedByName?: string,
) => {
  const { data } = await http.post(`/validation/${errorId}/resolve`, {
    resolution_note: note,
    resolved_by_name: resolvedByName || undefined,
    correction: correction || null,
  })
  return data
}

// These return absolute URLs used directly in <a href> / <img src>.
// We build them at call-time using window.location.origin so they stay
// correct on localhost, Tailscale, or any other host.
function apiBase(): string {
  if (typeof window !== 'undefined') return `${window.location.origin}/api/v1`
  return '/api/v1'
}

export const previewFileUrl = (fileId: string) => `${apiBase()}/files/${fileId}/preview`

export const getInactiveEmployees = async () => {
  const { data } = await http.get('/admin/inactive-employees')
  return data
}

// ── Reports ───────────────────────────────────────────────────────────────────

export const listReports = async (batchId: string) => {
  const { data } = await http.get(`/batches/${batchId}/reports`)
  return data as { items: GeneratedReport[] }
}

export const generateReport = async (batchId: string) => {
  const { data } = await http.post(`/batches/${batchId}/reports/generate`)
  return data
}

export const downloadReportUrl = (reportId: string) => `${apiBase()}/reports/${reportId}/download`

// ── Admin ─────────────────────────────────────────────────────────────────────

export const listEmployees = async () => {
  const { data } = await http.get('/admin/employees')
  return data as { items: Employee[]; total: number }
}

export const listPayrollPeriods = async () => {
  const { data } = await http.get('/admin/payroll-periods')
  return data as { items: PayrollPeriod[]; total: number }
}

export const listVendors = async () => {
  const { data } = await http.get('/admin/vendors')
  return data
}

export const clearBatchData = async () => {
  const { data } = await http.delete('/admin/clear-batch-data', { params: { confirm: 'CONFIRM' } })
  return data
}

export const clearAllData = async () => {
  const { data } = await http.delete('/admin/clear-all-data', { params: { confirm: 'DELETE_EVERYTHING' } })
  return data
}

// ── Approvals ─────────────────────────────────────────────────────────────────

export const listApprovals = async (batchId: string) => {
  const { data } = await http.get(`/batches/${batchId}/approvals`)
  return data
}

export const updateApproval = async (submissionId: string, body: {
  approval_status: string
  approver_name?: string
  approver_email?: string
  notes?: string
}) => {
  const { data } = await http.post(`/submissions/${submissionId}/approve`, body)
  return data
}
