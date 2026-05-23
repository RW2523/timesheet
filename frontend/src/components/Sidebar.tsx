'use client'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import {
  LayoutDashboard, Upload, FolderOpen, CheckCircle2, AlertTriangle,
  FileSpreadsheet, Settings, Users, Clock,
} from 'lucide-react'
import clsx from 'clsx'

const nav = [
  { href: '/', label: 'Dashboard', icon: LayoutDashboard },
  { href: '/upload', label: 'Upload ZIP', icon: Upload },
  { href: '/batches', label: 'Batches', icon: FolderOpen },
  { href: '/admin', label: 'Admin Settings', icon: Settings },
]

export default function Sidebar() {
  const pathname = usePathname()

  return (
    <aside className="w-60 bg-brand-900 text-white flex flex-col shrink-0 h-screen">
      {/* Logo */}
      <div className="px-5 py-5 border-b border-blue-800">
        <div className="flex items-center gap-2">
          <Clock className="w-6 h-6 text-blue-300" />
          <div>
            <p className="font-bold text-sm leading-tight">Ajace TimeSheet</p>
            <p className="text-xs text-blue-300">AI Bot</p>
          </div>
        </div>
      </div>

      {/* Navigation */}
      <nav className="flex-1 px-3 py-4 space-y-1">
        {nav.map(({ href, label, icon: Icon }) => {
          const active = pathname === href || (href !== '/' && pathname.startsWith(href))
          return (
            <Link
              key={href}
              href={href}
              className={clsx(
                'flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-colors',
                active
                  ? 'bg-blue-700 text-white font-medium'
                  : 'text-blue-200 hover:bg-blue-800 hover:text-white',
              )}
            >
              <Icon className="w-4 h-4 shrink-0" />
              {label}
            </Link>
          )
        })}
      </nav>

      {/* Footer */}
      <div className="px-5 py-3 border-t border-blue-800">
        <p className="text-xs text-blue-400">DGX Spark · Local Mode</p>
      </div>
    </aside>
  )
}
