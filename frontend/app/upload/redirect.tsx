"use client";

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';

export default function UploadRedirect() {
  const router = useRouter();

  useEffect(() => {
    // Redirect to beta analysis page with upload tab
    router.replace('/beta?tab=upload');
  }, [router]);

  return (
    <div className="flex items-center justify-center min-h-screen">
      <div className="text-center">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600 mx-auto mb-4"></div>
        <p>Redirecting to Beta Analysis Platform...</p>
      </div>
    </div>
  );
}