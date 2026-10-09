'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { LOCAL_ROUTES } from '@/lib/routes';

export function LocalWorkspaceNavigation() {
  const pathname = usePathname();
  return <nav className="report-navigation" aria-label="Private workspace">
    {Object.entries(LOCAL_ROUTES).map(([name, href]) => <Link key={name} href={href}
      aria-current={pathname === href ? 'page' : undefined}>{name[0].toUpperCase() + name.slice(1)}</Link>)}
  </nav>;
}

export function LocalMobileNavigation() {
  const pathname = usePathname();
  // Remount on navigation so the disclosure never covers the destination page.
  return <details className="local-mobile-menu" key={pathname}>
    <summary>Menu</summary>
    <LocalWorkspaceNavigation />
  </details>;
}
