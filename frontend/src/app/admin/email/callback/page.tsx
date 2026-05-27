'use client'
/**
 * /admin/email/callback
 * 
 * Google OAuth2 redirects here after the user grants access.
 * We read the `code` from the URL, exchange it via the backend,
 * then redirect back to /admin?tab=email with a success/error message.
 */
import { Suspense, useEffect, useState } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import axios from 'axios'
import { Loader2, CheckCircle2, XCircle } from 'lucide-react'

const BASE = '/api/v1'

function CallbackContent() {
  const searchParams = useSearchParams()
  const router = useRouter()
  const [status, setStatus] = useState<'loading' | 'success' | 'error'>('loading')
  const [message, setMessage] = useState('')

  useEffect(() => {
    const code  = searchParams.get('code')
    const error = searchParams.get('error')
    const label = searchParams.get('state') || 'Gmail'

    if (error) {
      setStatus('error')
      setMessage(`Google declined access: ${error}`)
      return
    }
    if (!code) {
      setStatus('error')
      setMessage('No authorization code received from Google.')
      return
    }

    axios
      .post(`${BASE}/email/accounts/gmail/connect`, { code, label })
      .then((res) => {
        setStatus('success')
        setMessage(`Connected: ${res.data.email_address}`)
        setTimeout(() => router.push('/admin?tab=email'), 1500)
      })
      .catch((err) => {
        setStatus('error')
        setMessage(err.response?.data?.detail || 'Failed to connect Gmail account.')
      })
  }, [searchParams, router])

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50">
      <div className="bg-white rounded-2xl shadow-lg p-10 flex flex-col items-center gap-4 max-w-sm w-full">
        {status === 'loading' && (
          <>
            <Loader2 className="w-10 h-10 text-blue-500 animate-spin" />
            <p className="text-gray-600 text-sm font-medium">Connecting your Gmail…</p>
          </>
        )}
        {status === 'success' && (
          <>
            <CheckCircle2 className="w-10 h-10 text-green-500" />
            <p className="text-gray-800 font-semibold">{message}</p>
            <p className="text-xs text-gray-400">Redirecting back…</p>
          </>
        )}
        {status === 'error' && (
          <>
            <XCircle className="w-10 h-10 text-red-500" />
            <p className="text-red-700 font-semibold text-sm text-center">{message}</p>
            <button
              onClick={() => router.push('/admin?tab=email')}
              className="mt-2 text-sm text-blue-600 underline"
            >
              Back to Admin
            </button>
          </>
        )}
      </div>
    </div>
  )
}

export default function GmailCallbackPage() {
  return (
    <Suspense fallback={
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <Loader2 className="w-10 h-10 text-blue-500 animate-spin" />
      </div>
    }>
      <CallbackContent />
    </Suspense>
  )
}
