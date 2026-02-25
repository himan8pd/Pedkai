"use client"

import { redirect } from 'next/navigation'

export default function Home() {
  // Redirect to dashboard — frontend decomposed into routed pages (P1.8)
  redirect('/dashboard')
}
