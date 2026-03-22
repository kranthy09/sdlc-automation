import { useEffect, useRef, useState } from 'react'
import { getProgress, getResults, getReview } from '@/api/dynafit'
import { DynafitWebSocket } from '@/api/websocket'
import type { WSStatus } from '@/api/websocket'
import { useProgressStore } from '@/stores/progressStore'

const POLL_INTERVAL_MS = 3_000

export function useProgress(batchId: string) {
  const { init, dispatch, hydrate, hydrateFromProgress } = useProgressStore()
  const [wsStatus, setWsStatus] = useState<WSStatus>('connecting')
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  useEffect(() => {
    init(batchId)
    const ws = new DynafitWebSocket(batchId, dispatch, setWsStatus)
    ws.connect()

    let terminated = false

    // Poll durable phase progress every few seconds as a fallback.
    // This ensures the UI stays up to date even if WebSocket events are lost.
    const poll = () => {
      if (terminated) return
      getProgress(batchId)
        .then((data) => {
          hydrateFromProgress(data)
          // Check if pipeline finished — stop polling
          if (data.status === 'complete' || data.status === 'review_required') {
            fetchTerminalState()
          }
        })
        .catch(() => {
          // Endpoint unavailable — WebSocket handles live state
        })
    }

    // Initial fetch immediately
    poll()

    // Start polling interval
    pollRef.current = setInterval(poll, POLL_INTERVAL_MS)

    // Fetch terminal state for completed / review_required batches.
    const fetchTerminalState = () => {
      getResults(batchId)
        .then(async (data) => {
          if (data.status === 'complete') {
            hydrate(data, null)
            terminated = true
            ws.disconnect()
            stopPolling()
          } else if (data.status === 'review_required') {
            const review = await getReview(batchId).catch(() => null)
            hydrate(data, review)
            terminated = true
            ws.disconnect()
            stopPolling()
          }
          // status queued/running — leave WS + polling active
        })
        .catch(() => {
          // API unavailable — WS handles live state
        })
    }

    // Also check terminal state on mount
    fetchTerminalState()

    const stopPolling = () => {
      if (pollRef.current) {
        clearInterval(pollRef.current)
        pollRef.current = null
      }
    }

    return () => {
      terminated = true
      ws.disconnect()
      stopPolling()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [batchId])

  return { ...useProgressStore(), wsStatus }
}
