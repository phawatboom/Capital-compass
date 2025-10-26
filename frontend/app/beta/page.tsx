// "use client";

// import CompleteBetaAnalysisPage from './complete/page';

// export default function BetaPage() {
//   return <CompleteBetaAnalysisPage />;
// }

"use client";

import { BetaDashboard } from '@/components/beta/BetaDashboard';

export default function BetaPage() {
  return (
    <div className="container mx-auto px-4 py-8">
      <BetaDashboard />
    </div>
  );
}