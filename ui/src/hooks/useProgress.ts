import { useEffect, useState } from 'react'
import { getResults, getReview } from '@/api/dynafit'
import { DynafitWebSocket } from '@/api/websocket'
import type { WSStatus } from '@/api/websocket'
import { useProgressStore } from '@/stores/progressStore'

export function useProgress(batchId: string) {
  const { init, dispatch, hydrate } = useProgressStore()
  const [wsStatus, setWsStatus] = useState<WSStatus>('connecting')

  useEffect(() => {
    init(batchId)
    const ws = new DynafitWebSocket(batchId, dispatch, setWsStatus)
    ws.connect()

    // On reload the store is blank and no WS events will arrive for a finished
    // pipeline. Fetch current status from REST and hydrate the store so the UI
    // reflects whatever the worker already produced.
    getResults(batchId)
      .then(async (data) => {
        if (data.status === 'complete') {
          hydrate(data, null)
          ws.disconnect()
        } else if (data.status === 'review_required') {
          const review = await getReview(batchId).catch(() => null)
          hydrate(data, review)
          ws.disconnect()
        }
        // status queued/running — leave WS open to receive live events
      })
      .catch(() => {
        // API unavailable or batch not found — WS handles live state
      })

    return () => ws.disconnect()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [batchId])

  return { ...useProgressStore(), wsStatus }
}
