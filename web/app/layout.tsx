import type { Metadata } from 'next';
import { Geist, Geist_Mono } from 'next/font/google';
import './globals.css';

const geistSans = Geist({ variable: '--font-geist-sans', subsets: ['latin'] });
const geistMono = Geist_Mono({ variable: '--font-geist-mono', subsets: ['latin'] });

export const metadata: Metadata = {
  title: 'OneJournal — Private trading workspace',
  description: 'A synthetic preview of the OneJournal private trading journal and portfolio workspace.',
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html className="dark" lang="en"><body className={`${geistSans.variable} ${geistMono.variable}`}>{children}</body></html>;
}
