import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { uploadFile, runAnalysis } from '@/api/dynafit'
import type { UploadRequest, RunRequest } from '@/api/types'
import { useUIStore } from '@/stores/uiStore'

export function useUpload() {
  const [uploadId, setUploadId] = useState<string | null>(null)
  const { addNotification } = useUIStore()

  const upload = useMutation({
    mutationFn: (req: UploadRequest) => uploadFile(req),
    onSuccess: (data) => setUploadId(data.upload_id),
    onError: () => addNotification({ type: 'error', message: 'Upload failed. Check file format.' }),
  })

  const run = useMutation({
    mutationFn: (overrides?: RunRequest['config_overrides']) =>
      runAnalysis({ upload_id: uploadId!, config_overrides: overrides }),
    onError: () => addNotification({ type: 'error', message: 'Failed to start analysis.' }),
  })

  return { upload, run, uploadId }
}
