import type { WSMessage } from './types'

type MessageHandler = (msg: WSMessage) => void
type StatusHandler = (status: WSStatus) => void

export type WSStatus = 'connecting' | 'connected' | 'disconnected' | 'error'

const WS_BASE = import.meta.env.VITE_WS_URL ?? `ws://${window.location.host}/api/v1`
const MAX_RECONNECT_DELAY_MS = 30_000
const RECONNECT_BACKOFF_MULTIPLIER = 2
const MAX_RECONNECT_ATTEMPTS = 10

export class DynafitWebSocket {
  private ws: WebSocket | null = null
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null
  private reconnectDelay = 1_000
  private reconnectAttempts = 0
  private shouldReconnect = true
  private disconnectPending = false
  private status: WSStatus = 'disconnected'

  constructor(
    private readonly batchId: string,
    private readonly onMessage: MessageHandler,
    private readonly onStatus?: StatusHandler,
  ) {}

  connect(): void {
    this.shouldReconnect = true
    this.reconnectAttempts = 0
    this.disconnectPending = false
    this.openSocket()
  }

  disconnect(): void {
    this.shouldReconnect = false
    this.clearReconnectTimer()
    if (this.ws?.readyState === WebSocket.CONNECTING) {
      // Calling close() on a CONNECTING socket triggers a browser error
      // ("WebSocket is closed before the connection is established").
      // Set a flag so onopen closes it cleanly once the handshake completes.
      this.disconnectPending = true
      return
    }
    this.ws?.close(1000, 'client disconnect')
    this.ws = null
    this.setStatus('disconnected')
  }

  private openSocket(): void {
    const url = `${WS_BASE}/ws/progress/${this.batchId}`
    this.setStatus('connecting')

    const ws = new WebSocket(url)
    this.ws = ws

    ws.onopen = () => {
      if (this.ws !== ws) return // stale socket from a previous connect cycle
      if (this.disconnectPending) {
        this.disconnectPending = false
        ws.close(1000, 'client disconnect')
        this.ws = null
        this.setStatus('disconnected')
        return
      }
      this.reconnectDelay = 1_000
      this.setStatus('connected')
    }

    ws.onmessage = (event: MessageEvent<string>) => {
      if (this.ws !== ws) return // stale socket
      try {
        const msg = JSON.parse(event.data) as WSMessage
        this.onMessage(msg)

        // Stop reconnecting on any terminal event
        if (
          msg.event === 'complete' ||
          msg.event === 'review_required' ||
          msg.event === 'error'
        ) {
          this.shouldReconnect = false
        }
      } catch {
        // Malformed frame — ignore
      }
    }

    ws.onerror = () => {
      if (this.ws !== ws) return // stale socket
      this.setStatus('error')
    }

    ws.onclose = (event) => {
      if (this.ws !== ws) return // stale socket — never null out the live reference
      this.ws = null
      if (this.shouldReconnect && event.code !== 1000) {
        this.scheduleReconnect()
      } else {
        this.setStatus('disconnected')
      }
    }
  }

  private scheduleReconnect(): void {
    if (this.reconnectAttempts >= MAX_RECONNECT_ATTEMPTS) {
      this.setStatus('error')
      return
    }
    this.reconnectAttempts++
    this.setStatus('disconnected')
    this.clearReconnectTimer()
    this.reconnectTimer = setTimeout(() => {
      if (this.shouldReconnect) this.openSocket()
    }, this.reconnectDelay)
    this.reconnectDelay = Math.min(
      this.reconnectDelay * RECONNECT_BACKOFF_MULTIPLIER,
      MAX_RECONNECT_DELAY_MS,
    )
  }

  private clearReconnectTimer(): void {
    if (this.reconnectTimer !== null) {
      clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    }
  }

  private setStatus(s: WSStatus): void {
    if (this.status !== s) {
      this.status = s
      this.onStatus?.(s)
    }
  }

  getStatus(): WSStatus {
    return this.status
  }
}
