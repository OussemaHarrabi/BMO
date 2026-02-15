import type { Metadata } from 'next'

export const metadata: Metadata = {
  title: 'BMO - AI Personal Memory',
  description: 'Your AI-powered personal memory system',
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  )
}
