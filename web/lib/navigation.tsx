import type { AnchorHTMLAttributes } from 'react';

// Native navigation preserves new-tab, history and keyboard behavior. Each
// private destination verifies its session before mounting its data view.
export default function Link({ children, ...props }: AnchorHTMLAttributes<HTMLAnchorElement>) {
  return <a {...props}>{children}</a>;
}

export function usePathname() {
  return window.location.pathname;
}
