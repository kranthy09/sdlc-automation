import type { WSMessage } from './types'

type MessageHandler = (msg: WSMessage) => void
type StatusHandler = (status: WSStatus) => void

export type WSStatus = 'connecting' | 'connected' | 'disconnected' | 'error'

const WS_BASE = import.meta.env.VITE_WS_URL ?? `ws://${window.location.host}/api/v1`
const MAX_RECONNECT_DELAY_MS = 30_000
const RECONNECT_BACKOFF_MULTIPLIER = 2

export class DynafitWebSocket {
  private ws: WebSocket | null = null
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null
  private reconnectDelay = 1_000
  private shouldReconnect = true
  private status: WSStatus = 'disconnected'

  constructor(
    private readonly batchId: string,
    private readonly onMessage: MessageHandler,
    private readonly onStatus?: StatusHandler,
  ) {}

  connect(): void {
    this.shouldReconnect = true
    this.openSocket()
  }

  disconnect(): void {
    this.shouldReconnect = false
    this.clearReconnectTimer()
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
      this.reconnectDelay = 1_000
      this.setStatus('connected')
    }

    ws.onmessage = (event: MessageEvent<string>) => {
      try {
        const msg = JSON.parse(event.data) as WSMessage
        this.onMessage(msg)

        // Stop reconnecting once the pipeline is done or permanently failed
        if (msg.type === 'complete') {
          this.shouldReconnect = false
        }
      } catch {
        // Malformed frame — ignore
      }
    }

    ws.onerror = () => {
      this.setStatus('error')
    }

    ws.onclose = (event) => {
      this.ws = null
      if (this.shouldReconnect && event.code !== 1000) {
        this.scheduleReconnect()
      } else {
        this.setStatus('disconnected')
      }
    }
  }

  private scheduleReconnect(): void {
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
