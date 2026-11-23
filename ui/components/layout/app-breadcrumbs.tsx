"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { BackButton } from "@/components/navigation/back-button";
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "@/components/ui/breadcrumb";
import { shouldShowBack } from "@/lib/navigation-back";
import { breadcrumbsForPath } from "@/lib/navigation";

export function AppBreadcrumbs() {
  const pathname = usePathname();
  const crumbs = breadcrumbsForPath(pathname);
  const showBack = shouldShowBack(pathname);

  return (
    <div className="flex min-w-0 items-center gap-1.5 sm:gap-2">
      {showBack ? <BackButton compact className="-ml-1" /> : null}
      <Breadcrumb className="min-w-0">
        <BreadcrumbList>
          {crumbs.map((crumb, index) => {
            const isLast = index === crumbs.length - 1;
            return (
              <span key={`${crumb.label}-${index}`} className="contents">
                {index > 0 ? <BreadcrumbSeparator /> : null}
                <BreadcrumbItem>
                  {isLast || !crumb.href ? (
                    <BreadcrumbPage>{crumb.label}</BreadcrumbPage>
                  ) : (
                    <BreadcrumbLink asChild>
                      <Link href={crumb.href}>{crumb.label}</Link>
                    </BreadcrumbLink>
                  )}
                </BreadcrumbItem>
              </span>
            );
          })}
        </BreadcrumbList>
      </Breadcrumb>
    </div>
  );
}
