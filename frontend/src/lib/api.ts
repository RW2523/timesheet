import axios from 'axios'
import type {
  BatchSummary, DashboardStats, FileRecord, TimesheetEntry,
  ValidationError, ValidationListResponse, GeneratedReport,
  Employee, PayrollPeriod,
} from '@/types'

const BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api/v1'

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
  }
}

// ── Upload ────────────────────────────────────────────────────────────────────

export const uploadZip = async (
  file: File,
  payrollPeriodId?: string,
  notes?: string,
  onProgress?: (pct: number) => void,
) => {
  const form = new FormData()
  form.append('file', file)
  if (payrollPeriodId) form.append('payroll_period_id', payrollPeriodId)
  if (notes) form.append('notes', notes)

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

export const resolveValidationError = async (errorId: string, note?: string) => {
  const { data } = await http.post(`/validation/${errorId}/resolve`, { resolution_note: note })
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

export const downloadReportUrl = (reportId: string) => `${BASE}/reports/${reportId}/download`

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
