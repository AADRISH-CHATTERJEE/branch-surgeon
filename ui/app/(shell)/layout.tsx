import { AppShell } from "@/layouts/app-shell";

export default function ShellLayout({ children }: { children: React.ReactNode }) {
  return <AppShell>{children}</AppShell>;
}
