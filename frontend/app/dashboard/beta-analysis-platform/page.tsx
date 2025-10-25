'use client';

import { Suspense } from 'react';
import { useSearchParams } from 'next/navigation';
import { IntegratedWorkflow } from '@/components/beta/IntegratedWorkflow';

function BetaAnalysisPlatformContent() {
  const searchParams = useSearchParams();
  const fileId = searchParams.get('fileId');

  return (
    <div className="container mx-auto p-6">
      <div className="mb-6">
        <h1 className="text-3xl font-bold text-gray-900">Beta Analysis Platform</h1>
        <p className="text-gray-600 mt-2">
          Configure and run beta analysis on your data
        </p>
      </div>
      
      <IntegratedWorkflow fileId={fileId ? parseInt(fileId, 10) : undefined} />
    </div>
  );
}

export default function BetaAnalysisPlatformPage() {
  return (
    <Suspense fallback={
      <div className="container mx-auto p-6">
        <div className="flex items-center justify-center h-64">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div>
          <span className="ml-2 text-gray-600">Loading beta analysis platform...</span>
        </div>
      </div>
    }>
      <BetaAnalysisPlatformContent />
    </Suspense>
  );
}