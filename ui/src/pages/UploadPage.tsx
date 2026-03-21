import { PageHeader } from '@/components/layout/PageHeader'
import { Skeleton } from '@/components/ui/Skeleton'

export default function UploadPage() {
  return (
    <div>
      <PageHeader
        title="Upload Requirements"
        description="Upload a DOCX, PDF, or TXT file to begin DYNAFIT analysis"
      />
      <div className="px-6 space-y-4">
        <Skeleton className="h-48 rounded-xl" />
        <Skeleton className="h-32 rounded-xl" />
      </div>
    </div>
  )
}
