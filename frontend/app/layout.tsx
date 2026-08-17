import './globals.css';
import type { Metadata } from 'next';
import { AuthProvider } from './AuthProvider';

export const metadata: Metadata = {
  title: 'BookTranslate AI Lab',
  description: 'Technical translation operations workspace',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <AuthProvider>{children}</AuthProvider>
      </body>
    </html>
  );
}
