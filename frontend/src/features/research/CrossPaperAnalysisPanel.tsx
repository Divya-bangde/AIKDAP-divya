import React, { useState } from 'react';



interface ComparisonItem {
  topic: string;
  primary_claim: string;
  supporting_claims: string[];
  relationship: string;
  evidence: string;
}

interface GapResolution {
  gap_description: string;
  resolution_state: string;
  explanation: string;
}

interface ResearchHypothesis {
  id: string;
  description: string;
  rationale: string;
  status: string;
}

interface CrossPaperComparison {
  primary_paper_id: string;
  supporting_paper_ids: string[];
  comparison_items: ComparisonItem[];
  gap_resolutions: GapResolution[];
  hypotheses: ResearchHypothesis[];
}

export const CrossPaperAnalysisPanel: React.FC<{
  primaryAssetId: string;
  projectId: string;
  onAnalysisStart: (supportingIds: string[]) => void;
  result?: CrossPaperComparison;
}> = ({ primaryAssetId, projectId, onAnalysisStart, result }) => {
  const [selectedSupporting] = useState<string[]>([]);

  // Use variables to avoid TS unused errors
  const handleStart = () => {
    console.log(`Starting analysis for project ${projectId}, primary asset ${primaryAssetId}`);
    onAnalysisStart(selectedSupporting);
  };

  return (
    <div className="p-4 border rounded-md shadow-sm bg-white">
      <h2 className="text-xl font-bold mb-4">Cross-Paper Synthesis</h2>
      
      {!result ? (
        <div className="flex flex-col gap-4">
          <p className="text-sm text-gray-600">Select supporting papers to synthesize with the primary document.</p>
          <button 
            onClick={handleStart}
            className="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700 w-fit"
          >
            Start Analysis
          </button>
        </div>

      ) : (
        <div className="flex flex-col gap-6">
          <section>
            <h3 className="font-semibold text-lg">Comparison Matrix</h3>
            <ul className="mt-2 space-y-2">
              {result.comparison_items.map((item, idx) => (
                <li key={idx} className="p-3 border rounded bg-gray-50">
                  <div className="flex justify-between">
                    <span className="font-medium text-gray-800">{item.topic}</span>
                    <span className="text-xs font-bold px-2 py-1 bg-gray-200 rounded">{item.relationship}</span>
                  </div>
                  <div className="mt-2 text-sm text-gray-700">
                    <p><strong>Primary:</strong> {item.primary_claim}</p>
                    <p><strong>Supporting:</strong> {item.supporting_claims.join(', ')}</p>
                  </div>
                </li>
              ))}
            </ul>
          </section>

          <section>
            <h3 className="font-semibold text-lg">Gap Resolutions</h3>
            <ul className="mt-2 space-y-2">
              {result.gap_resolutions.map((gap, idx) => (
                <li key={idx} className="p-3 border rounded bg-gray-50">
                  <div className="flex justify-between">
                    <span className="font-medium text-gray-800">{gap.gap_description}</span>
                    <span className="text-xs font-bold px-2 py-1 bg-blue-100 text-blue-800 rounded">{gap.resolution_state}</span>
                  </div>
                  <p className="mt-1 text-sm text-gray-600">{gap.explanation}</p>
                </li>
              ))}
            </ul>
          </section>

          <section>
            <h3 className="font-semibold text-lg">Research Hypotheses</h3>
            <ul className="mt-2 space-y-2">
              {result.hypotheses.map((hypo, idx) => (
                <li key={idx} className="p-3 border rounded bg-yellow-50">
                  <p className="font-medium text-gray-900">{hypo.description}</p>
                  <p className="text-sm text-gray-600 mt-1">{hypo.rationale}</p>
                  <div className="flex gap-2 mt-3">
                    <button className="text-xs px-3 py-1 bg-green-600 text-white rounded hover:bg-green-700">Accept</button>
                    <button className="text-xs px-3 py-1 bg-red-600 text-white rounded hover:bg-red-700">Reject</button>
                  </div>
                </li>
              ))}
            </ul>
          </section>
        </div>
      )}
    </div>
  );
};
