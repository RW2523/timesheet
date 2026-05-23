import clsx from 'clsx'

const STATUS_STYLES: Record<string, string> = {
  // Batch statuses
  UPLOADED: 'bg-gray-100 text-gray-700',
  PROCESSING: 'bg-blue-100 text-blue-700',
  NEEDS_REVIEW: 'bg-yellow-100 text-yellow-800',
  PAYROLL_READY: 'bg-green-100 text-green-700',
  FAILED: 'bg-red-100 text-red-700',
  COMPLETED: 'bg-green-100 text-green-700',
  // File statuses
  DETECTED: 'bg-gray-100 text-gray-600',
  PARSED: 'bg-blue-100 text-blue-700',
  OCR_PENDING: 'bg-purple-100 text-purple-700',
  NORMALIZED: 'bg-indigo-100 text-indigo-700',
  DUPLICATE: 'bg-orange-100 text-orange-700',
  IGNORED_NOISE: 'bg-gray-100 text-gray-500',
  // Match statuses
  AUTO_MATCHED: 'bg-green-100 text-green-700',
  MANUALLY_MATCHED: 'bg-teal-100 text-teal-700',
  NOT_MATCHED: 'bg-red-100 text-red-700',
  // Approval / Validation
  PENDING: 'bg-yellow-100 text-yellow-800',
  APPROVED: 'bg-green-100 text-green-700',
  REJECTED: 'bg-red-100 text-red-700',
  PASSED: 'bg-green-100 text-green-700',
  NOT_READY: 'bg-red-100 text-red-700',
  READY: 'bg-green-100 text-green-700',
  OPEN: 'bg-yellow-100 text-yellow-800',
  RESOLVED: 'bg-gray-100 text-gray-600',
}

export default function StatusBadge({ status }: { status: string }) {
  return (
    <span className={clsx('inline-flex items-center px-2 py-0.5 rounded text-xs font-medium', STATUS_STYLES[status] ?? 'bg-gray-100 text-gray-700')}>
      {status.replace(/_/g, ' ')}
    </span>
  )
}
