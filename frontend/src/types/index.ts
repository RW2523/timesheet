export interface BatchSummary {
  id: string
  source_name: string
  source_type: string
  status: string
  total_files: number
  processed_files: number
  failed_files: number
  ignored_files: number
  duplicate_files: number
  review_required_files: number
  payroll_ready_count: number
  created_at: string
  updated_at: string
  summary_json?: Record<string, unknown>
  filter_period_start?: string
  filter_period_end?: string
  current_file?: string
  current_stage?: string
}

export interface DashboardStats {
  total_batches: number
  processing_batches: number
  needs_review_batches: number
  payroll_ready_batches: number
  failed_batches: number
  open_blockers: number
  open_warnings: number
}

export interface FileRecord {
  id: string
  batch_id: string
  folder_path?: string
  file_name: string
  file_ext?: string
  file_size_bytes?: number
  file_hash?: string
  detected_employee_name?: string
  detected_vendor_name?: string
  detected_period_text?: string
  matched_employee_id?: string
  match_confidence?: number
  match_status: string
  parser_name?: string
  ocr_required: boolean
  is_duplicate: boolean
  is_noise_file: boolean
  is_timesheet_candidate: boolean
  processing_status: string
  alerts_json?: unknown
  created_at: string
}

export interface TimesheetEntry {
  id: string
  submission_id: string
  employee_id: string
  work_date: string
  day_of_week?: string
  in_time?: string
  out_time?: string
  break_minutes: number
  entered_hours?: number
  calculated_hours?: number
  regular_hours: number
  overtime_hours: number
  entry_type: string
  leave_type?: string
  is_holiday: boolean
  holiday_name?: string
  validation_status: string
  created_at: string
}

export interface ValidationError {
  id: string
  batch_id?: string
  file_id?: string
  submission_id?: string
  entry_id?: string
  employee_id?: string
  rule_code: string
  severity: 'BLOCKER' | 'ERROR' | 'WARNING' | 'INFO'
  message: string
  expected_value?: string
  actual_value?: string
  action_required?: string
  assigned_to_role?: string
  status: string
  resolved_by?: string
  resolved_at?: string
  created_at: string
}

export interface ValidationListResponse {
  items: ValidationError[]
  total: number
  blocker_count: number
  error_count: number
  warning_count: number
  info_count: number
}

export interface GeneratedReport {
  id: string
  batch_id?: string
  payroll_run_id?: string
  report_type: string
  file_name: string
  generated_by?: string
  created_at: string
}

export interface Employee {
  id: string
  full_name: string
  email?: string
  employee_code?: string
  employee_type?: string
  vendor_id?: string
  is_active: boolean
}

export interface PayrollPeriod {
  id: string
  period_key: string
  start_date: string
  end_date: string
  cutoff_date: string
  status: string
}
