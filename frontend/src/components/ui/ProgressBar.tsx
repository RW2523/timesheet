interface Props {
  value: number
  label?: string
  color?: 'blue' | 'green' | 'red' | 'yellow'
}

const COLORS = {
  blue: 'bg-blue-500',
  green: 'bg-green-500',
  red: 'bg-red-500',
  yellow: 'bg-yellow-400',
}

export default function ProgressBar({ value, label, color = 'blue' }: Props) {
  const pct = Math.min(100, Math.max(0, value))
  return (
    <div className="w-full">
      {label && (
        <div className="flex justify-between text-xs text-gray-600 mb-1">
          <span>{label}</span>
          <span>{pct}%</span>
        </div>
      )}
      <div className="h-2 bg-gray-200 rounded-full overflow-hidden">
        <div
          className={`h-full rounded-full transition-all duration-300 ${COLORS[color]}`}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  )
}
