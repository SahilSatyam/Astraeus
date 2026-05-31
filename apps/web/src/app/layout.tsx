import type { Metadata } from 'next';
import { JetBrains_Mono, Inter } from 'next/font/google';
import './globals.css';
import '@/styles/tokens.css';
import { Providers } from '@/components/providers';
import { Sidebar } from '@/components/sidebar';
import { StatusBar } from '@/components/status-bar';
import { CommandPalette } from '@/components/command-palette';

const inter = Inter({
  variable: '--font-inter',
  subsets: ['latin'],
});

const jetbrainsMono = JetBrains_Mono({
  variable: '--font-jetbrains',
  subsets: ['latin'],
});

export const metadata: Metadata = {
  title: 'Astraeus — Operator Terminal',
  description: 'Institutional-grade quantitative trading platform',
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${inter.variable} ${jetbrainsMono.variable} h-full`}
      data-theme="dark"
    >
      <body className="h-full flex flex-col bg-[var(--color-bg)] text-[var(--color-text-primary)] text-[13px] leading-[var(--line-height-tight)] antialiased">
        <Providers>
          <div className="flex flex-1 overflow-hidden">
            <Sidebar />
            <main className="flex-1 overflow-auto p-4">{children}</main>
          </div>
          <StatusBar />
          <CommandPalette />
        </Providers>
      </body>
    </html>
  );
}
