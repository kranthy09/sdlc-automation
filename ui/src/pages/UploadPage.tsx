import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { PageHeader } from '@/components/layout/PageHeader'
import { DropZone } from '@/components/upload/DropZone'
import { UploadConfigForm, type UploadConfig } from '@/components/upload/UploadConfigForm'
import { Button } from '@/components/ui/Button'
import { Card } from '@/components/ui/Card'
import { useUpload } from '@/hooks/useUpload'
import { useUIStore } from '@/stores/uiStore'

const DEFAULT_CONFIG: UploadConfig = {
  product: 'd365_fo',
  country: 'DE',
  wave: 1,
  fitConfidenceThreshold: 0.75,
  autoApproveWithHistory: false,
}

export default function UploadPage() {
  const navigate = useNavigate()
  const [file, setFile] = useState<File | null>(null)
  const [config, setConfig] = useState<UploadConfig>(DEFAULT_CONFIG)
  const { upload, run, uploadId } = useUpload()
  const { setActiveBatchId } = useUIStore()

  const busy = upload.isPending || run.isPending

  const handleStart = async () => {
    if (!file || !uploadId) return

    const res = await run.mutateAsync({
      fit_confidence_threshold: config.fitConfidenceThreshold,
      auto_approve_with_history: config.autoApproveWithHistory,
    })

    setActiveBatchId(res.batch_id)
    navigate(`/progress/${res.batch_id}`)
  }

  const canStart = !!file && !!uploadId && !!config.country && !busy

  return (
    <div>
      <PageHeader
        title="Upload Requirements"
        description="Upload a DOCX, PDF, XLSX, or TXT file to begin REQFIT analysis"
      />
      <div className="px-6 pb-6 space-y-4 max-w-2xl">
        {/* Drop zone */}
        <Card>
          <DropZone
            file={file}
            onFile={(f) => {
              setFile(f)
              // Auto-upload on file selection
              upload.mutate({
                file: f,
                product: config.product,
                country: config.country,
                wave: config.wave,
              })
            }}
            onClear={() => setFile(null)}
            disabled={busy}
          />
          {upload.isSuccess && (
            <p className="mt-2 text-xs text-fit-text">
              {upload.data.status === 'already_exists' ? 'Already uploaded' : 'Uploaded'} · {upload.data.detected_format} detected
            </p>
          )}
        </Card>

        {/* Config form */}
        <Card header="Analysis configuration">
          <UploadConfigForm value={config} onChange={setConfig} disabled={busy} />
        </Card>

        {/* CTA */}
        <div className="flex justify-end">
          <Button
            size="lg"
            onClick={handleStart}
            disabled={!canStart}
            loading={busy}
          >
            Start analysis
          </Button>
        </div>
      </div>
    </div>
  )
}
