"use client"

/** THE page header: back button + title (+ optional right slot). */
import { ReactNode } from "react"
import { useRouter } from "next/navigation"

export function PageHeader({
  title,
  backHref,
  right,
}: {
  title: string
  /** omit → router.back() */
  backHref?: string
  right?: ReactNode
}) {
  const router = useRouter()
  return (
    <div className="flex items-center gap-3 mb-4">
      <button
        onClick={() => (backHref ? router.push(backHref) : router.back())}
        aria-label="Back"
        className="w-9 h-9 rounded-full bg-bg flex items-center justify-center text-ink text-lg shrink-0"
      >
        ←
      </button>
      <h1 className="text-xl font-bold text-ink flex-1">{title}</h1>
      {right}
    </div>
  )
}
