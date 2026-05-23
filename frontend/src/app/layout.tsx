import type { Metadata } from 'next'
import './globals.css'
import Sidebar from '@/components/Sidebar'
import QueryProvider from '@/components/QueryProvider'

export const metadata: Metadata = {
  title: 'Ajace TimeSheet AI Bot',
  description: 'Local, GPU-accelerated timesheet processing',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="flex h-screen overflow-hidden">
        <QueryProvider>
          <Sidebar />
          <main className="flex-1 overflow-auto bg-gray-50">
            {children}
          </main>
        </QueryProvider>
      </body>
    </html>
  )
}
