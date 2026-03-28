import { lazy, Suspense } from 'react'
import { createBrowserRouter, Navigate, RouterProvider } from 'react-router-dom'
import { AppShell } from '@/components/layout/AppShell'
import { Skeleton } from '@/components/ui/Skeleton'

// ─── Lazy-loaded pages ────────────────────────────────────────────────────────
const DashboardPage = lazy(() => import('@/pages/DashboardPage'))
const UploadPage = lazy(() => import('@/pages/UploadPage'))
const ProgressPage = lazy(() => import('@/pages/ProgressPage'))
const ResultsPage = lazy(() => import('@/pages/ResultsPage'))
const ReviewPage = lazy(() => import('@/pages/ReviewPage'))
const FeatureDetailPage = lazy(() => import('@/pages/FeatureDetailPage'))
const AtomDetailPage = lazy(() => import('@/pages/AtomDetailPage'))
const ComparePage = lazy(() => import('@/pages/ComparePage'))
const SettingsPage = lazy(() => import('@/pages/SettingsPage'))

// ─── Page-level loading fallback ──────────────────────────────────────────────
function PageLoader() {
  return (
    <div className="flex flex-col gap-4 p-6">
      <Skeleton className="h-8 w-64" />
      <Skeleton className="h-4 w-96" />
      <div className="mt-4 grid grid-cols-4 gap-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} className="h-28 rounded-xl" />
        ))}
      </div>
      <Skeleton className="mt-4 h-64 rounded-xl" />
    </div>
  )
}

// ─── Router ───────────────────────────────────────────────────────────────────
const router = createBrowserRouter([
  {
    path: '/',
    element: <AppShell />,
    children: [
      { index: true, element: <Navigate to="/dashboard" replace /> },
      {
        path: 'dashboard',
        element: (
          <Suspense fallback={<PageLoader />}>
            <DashboardPage />
          </Suspense>
        ),
      },
      {
        path: 'upload',
        element: (
          <Suspense fallback={<PageLoader />}>
            <UploadPage />
          </Suspense>
        ),
      },
      {
        path: 'progress/:batchId',
        element: (
          <Suspense fallback={<PageLoader />}>
            <ProgressPage />
          </Suspense>
        ),
      },
      {
        path: 'results/:batchId',
        element: (
          <Suspense fallback={<PageLoader />}>
            <ResultsPage />
          </Suspense>
        ),
      },
      {
        path: 'review/:batchId',
        element: (
          <Suspense fallback={<PageLoader />}>
            <ReviewPage />
          </Suspense>
        ),
      },
      {
        path: 'features/:batchId',
        element: (
          <Suspense fallback={<PageLoader />}>
            <FeatureDetailPage />
          </Suspense>
        ),
      },
      {
        path: 'atom/:batchId/:atomId',
        element: (
          <Suspense fallback={<PageLoader />}>
            <AtomDetailPage />
          </Suspense>
        ),
      },
      {
        path: 'compare',
        element: (
          <Suspense fallback={<PageLoader />}>
            <ComparePage />
          </Suspense>
        ),
      },
      {
        path: 'settings',
        element: (
          <Suspense fallback={<PageLoader />}>
            <SettingsPage />
          </Suspense>
        ),
      },
    ],
  },
])

export default function App() {
  return <RouterProvider router={router} />
}
