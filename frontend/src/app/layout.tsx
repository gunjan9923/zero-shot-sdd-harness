import type { Metadata } from 'next'
import './globals.css'

export const metadata: Metadata = {
  title: 'Analyst Workspace',
  description: 'Local CSV / Excel data-analysis agent — upload, ask, get answers with the exact code.',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-gray-50 text-gray-900 antialiased">{children}</body>
    </html>
  )
}
