/**
 * LAKO — useDashboard Hook
 * Polls GET /api/dashboard/stats every 30s.
 * Fetches GET /api/dashboard/recent-activity on load and after each refresh.
 * Session 11: Created.
 */

import { useState, useEffect, useCallback, useRef } from 'react'

const POLL_INTERVAL_MS = 30_000

export default function useDashboard() {
  const [stats, setStats]       = useState(null)
  const [activity, setActivity] = useState([])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError]       = useState(null)
  const [lastUpdated, setLastUpdated] = useState(null)   // Date object
  const intervalRef = useRef(null)

  const fetchAll = useCallback(async () => {
    setIsLoading(true)
    setError(null)
    try {
      const [statsRes, activityRes] = await Promise.all([
        fetch('/api/dashboard/stats'),
        fetch('/api/dashboard/recent-activity'),
      ])
      if (!statsRes.ok || !activityRes.ok) {
        throw new Error('Dashboard endpoint error')
      }
      const [statsData, activityData] = await Promise.all([
        statsRes.json(),
        activityRes.json(),
      ])
      setStats(statsData)
      setActivity(activityData)
      setLastUpdated(new Date())
    } catch (err) {
      setError(err.message || 'Failed to load dashboard data')
    } finally {
      setIsLoading(false)
    }
  }, [])

  // Initial fetch + polling
  useEffect(() => {
    fetchAll()
    intervalRef.current = setInterval(fetchAll, POLL_INTERVAL_MS)
    return () => clearInterval(intervalRef.current)
  }, [fetchAll])

  return { stats, activity, isLoading, error, refresh: fetchAll, lastUpdated }
}
