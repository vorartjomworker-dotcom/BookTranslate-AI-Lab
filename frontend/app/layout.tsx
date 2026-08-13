import './globals.css';
import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'BookTranslate AI Lab',
  description: 'AI-powered technical book translation workspace',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
