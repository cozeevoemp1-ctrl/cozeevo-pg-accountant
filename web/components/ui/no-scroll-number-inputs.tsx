"use client"

import { useEffect } from "react"

export function NoScrollNumberInputs() {
  useEffect(() => {
    function handler(e: WheelEvent) {
      const el = document.activeElement as HTMLInputElement | null
      if (el?.type === "number") el.blur()
    }
    document.addEventListener("wheel", handler, { passive: true })
    return () => document.removeEventListener("wheel", handler)
  }, [])
  return null
}
