import { useState, useRef } from "react";
import { Upload, FileText, FileJson } from "lucide-react";
import { importCSV, importJSON } from "../api/client";

interface ImportResult {
  batch_id?: number;
  imported: number;
  duplicates?: number;
  flagged: number;
  errors: number;
}

export default function ImportPage() {
  const [result, setResult] = useState<ImportResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  const handleFile = async (file: File) => {
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      let data: ImportResult;
      if (file.name.endsWith(".csv")) {
        data = await importCSV(file);
      } else if (file.name.endsWith(".json")) {
        data = await importJSON(file);
      } else {
        setError("Only .csv and .json files are supported.");
        return;
      }
      setResult(data);
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })
        ?.response?.data?.detail ?? "Import failed.";
      setError(msg);
    } finally {
      setLoading(false);
    }
  };

  const onFileInput = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) handleFile(file);
    e.target.value = "";
  };

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files?.[0];
    if (file) handleFile(file);
  };

  return (
    <div className="p-6 max-w-2xl mx-auto">
      <h1 className="text-xl font-bold text-white mb-1">Import Data</h1>
      <p className="text-sm text-gray-500 mb-6">
        Import public-source records from CSV or JSON datasets. Max 50 MB.
        Optional media attachments must be relative paths inside the configured import root.
      </p>

      {/* Schema format guide (neutral placeholders only) */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-6">
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
          <div className="flex items-center gap-2 mb-2 text-sm font-semibold text-gray-300">
            <FileText size={15} /> CSV schema
          </div>
          <pre className="text-xs text-gray-500 leading-relaxed overflow-x-auto">
{`text,channel,created_at,sender,source_message_id,image_attachment
"[record text]",source_channel,2025-01-15T10:00:00Z,sender_id,1001,sample.png`}
          </pre>
        </div>
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
          <div className="flex items-center gap-2 mb-2 text-sm font-semibold text-gray-300">
            <FileJson size={15} /> JSON schema
          </div>
          <pre className="text-xs text-gray-500 leading-relaxed overflow-x-auto">
{`[
  {
    "text": "[record text]",
    "channel": "source_channel",
    "created_at": "2025-01-15T10:00:00Z",
    "sender": "sender_id",
    "source_message_id": 1001,
    "image_attachment": "sample.png"
  }
]`}
          </pre>
        </div>
      </div>

      {/* Drop zone */}
      <div
        onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
        onDragLeave={() => setDragOver(false)}
        onDrop={onDrop}
        onClick={() => fileRef.current?.click()}
        className={`border-2 border-dashed rounded-xl py-14 text-center cursor-pointer transition-colors ${
          dragOver
            ? "border-blue-500 bg-blue-950/20"
            : "border-gray-700 hover:border-gray-600 bg-gray-900/40"
        }`}
      >
        <Upload size={28} className="mx-auto mb-3 text-gray-500" />
        <p className="text-sm text-gray-400">
          Drop a <strong className="text-gray-300">.csv</strong> or{" "}
          <strong className="text-gray-300">.json</strong> file here
        </p>
        <p className="text-xs text-gray-600 mt-1">or click to browse</p>
        <input
          ref={fileRef}
          type="file"
          accept=".csv,.json"
          onChange={onFileInput}
          className="hidden"
        />
      </div>

      {loading && (
        <div className="mt-5 text-center text-sm text-gray-400">Processing file…</div>
      )}

      {error && (
        <div className="mt-5 bg-red-950/30 border border-red-700/30 text-red-400 text-sm rounded-xl px-4 py-3">
          {error}
        </div>
      )}

      {result && (
        <div className="mt-5 bg-green-950/30 border border-green-700/30 rounded-xl px-5 py-4">
          <div className="flex items-center justify-between mb-2">
            <p className="text-green-400 font-semibold text-sm">Import complete</p>
            {result.batch_id !== undefined && (
              <span className="text-xs font-mono text-gray-400">Batch #{result.batch_id}</span>
            )}
          </div>
          <div className="grid grid-cols-4 gap-3 text-center">
            <div>
              <p className="text-2xl font-bold text-white">{result.imported}</p>
              <p className="text-xs text-gray-500">Imported</p>
            </div>
            <div>
              <p className="text-2xl font-bold text-blue-400">{result.duplicates ?? 0}</p>
              <p className="text-xs text-gray-500">Duplicates</p>
            </div>
            <div>
              <p className="text-2xl font-bold text-red-400">{result.flagged}</p>
              <p className="text-xs text-gray-500">Flagged</p>
            </div>
            <div>
              <p className="text-2xl font-bold text-yellow-400">{result.errors}</p>
              <p className="text-xs text-gray-500">Errors</p>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
