import { useState, useEffect } from "react";
import { API_BASE } from "../api/client";

interface StagedFile {
  filename: string;
  size_kb: number;
}

export function AdminPage() {
  const [uploadStatus, setUploadStatus] = useState<{ type: 'success' | 'error' | 'info'; message: string } | null>(null);
  const [isPipelineRunning, setIsPipelineRunning] = useState(false);
  const [pipelineMessage, setPipelineMessage] = useState("");
  
  const [files, setFiles] = useState<StagedFile[]>([]);
  const [uploadSupplier, setUploadSupplier] = useState("");
  const [uploadType, setUploadType] = useState<"hotels" | "rooms">("hotels");

  useEffect(() => {
    checkPipelineStatus();
    fetchFiles();
    const interval = setInterval(checkPipelineStatus, 5000);
    return () => clearInterval(interval);
  }, []);

  const fetchFiles = async () => {
    try {
      const res = await fetch(`${API_BASE}/admin/files`);
      const data = await res.json();
      setFiles(data.files || []);
    } catch (err) {
      console.error("Failed to fetch files", err);
    }
  };

  const checkPipelineStatus = async () => {
    try {
      const res = await fetch(`${API_BASE}/admin/pipeline-status`);
      const data = await res.json();
      setPipelineMessage(data.message);
      setIsPipelineRunning(data.status === "running");
    } catch (err) {
      console.error("Failed to check pipeline status", err);
    }
  };



  const handleDeleteFile = async (filename: string) => {
    if (!confirm(`Are you sure you want to delete ${filename}?`)) return;
    try {
      const res = await fetch(`${API_BASE}/admin/files/${filename}`, {
        method: "DELETE",
      });
      if (res.ok) {
        setUploadStatus({ type: 'success', message: `Deleted ${filename}` });
        fetchFiles();
        handleRunPipeline(); // Auto run pipeline
      } else {
        const data = await res.json();
        setUploadStatus({ type: 'error', message: data.detail || 'Delete failed' });
      }
    } catch (err) {
      setUploadStatus({ type: 'error', message: 'Network error during delete' });
    }
  };

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    if (!e.target.files || e.target.files.length === 0) return;
    if (!uploadSupplier.trim()) {
      alert("Please enter a supplier name first");
      return;
    }

    const file = e.target.files[0];
    setUploadStatus({ type: 'info', message: `Uploading ${file.name}...` });
    
    const formData = new FormData();
    formData.append("file", file);
    formData.append("supplier_name", uploadSupplier);
    formData.append("data_type", uploadType);

    try {
      const res = await fetch(`${API_BASE}/admin/upload-supplier`, {
        method: "POST",
        body: formData,
      });
      
      const data = await res.json();
      if (res.ok) {
        setUploadStatus({ type: 'success', message: data.message });
        fetchFiles();
        handleRunPipeline(); // Auto run pipeline after upload
      } else {
        setUploadStatus({ type: 'error', message: data.detail || 'Upload failed' });
      }
    } catch (err) {
      setUploadStatus({ type: 'error', message: 'Network error during upload' });
    }
    
    // Clear input
    e.target.value = '';
  };

  const handleRunPipeline = async () => {
    setIsPipelineRunning(true);
    setUploadStatus({ type: 'info', message: 'Starting pipeline...' });
    
    try {
      const res = await fetch(`${API_BASE}/admin/trigger-pipeline`, {
        method: "POST",
      });
      const data = await res.json();
      if (res.ok) {
        setUploadStatus({ type: 'success', message: data.message });
        checkPipelineStatus();
      } else {
        setUploadStatus({ type: 'error', message: data.detail || 'Failed to start pipeline' });
        setIsPipelineRunning(false);
      }
    } catch (err) {
      setUploadStatus({ type: 'error', message: 'Network error triggering pipeline' });
      setIsPipelineRunning(false);
    }
  };


  return (
    <div className="mx-auto max-w-5xl px-4 py-12">
      <h1 className="text-3xl font-bold text-ink-900 mb-8">Data Pipeline Admin</h1>

      {uploadStatus && (
        <div className={`mb-6 p-4 rounded-md ${
          uploadStatus.type === 'success' ? 'bg-green-50 text-green-800 border border-green-200' :
          uploadStatus.type === 'error' ? 'bg-red-50 text-red-800 border border-red-200' :
          'bg-blue-50 text-blue-800 border border-blue-200'
        }`}>
          {uploadStatus.message}
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        
        <div className="md:col-span-2 flex flex-col gap-6">
          <div className="bg-white p-6 rounded shadow-sm border border-ink-200">
            <h2 className="text-xl font-semibold mb-4">Current File Stack</h2>
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead>
                  <tr className="border-b">
                    <th className="pb-2 font-medium">Filename</th>
                    <th className="pb-2 font-medium">Size</th>
                    <th className="pb-2 font-medium">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {files.length === 0 ? (
                    <tr>
                      <td colSpan={3} className="py-4 text-center text-ink-500">No files uploaded yet.</td>
                    </tr>
                  ) : (
                    files.map(f => (
                      <tr key={f.filename} className="border-b border-ink-100 last:border-0">
                        <td className="py-3 font-medium text-ink-900">{f.filename}</td>
                        <td className="py-3 text-ink-500">{f.size_kb} KB</td>
                        <td className="py-3">
                          <button onClick={() => handleDeleteFile(f.filename)} className="text-red-600 hover:text-red-800 font-medium">
                            Delete
                          </button>
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>

          <div className="bg-white p-6 rounded shadow-sm border border-ink-200">
            <h2 className="text-xl font-semibold mb-4">Upload New Supplier</h2>
            <p className="text-sm text-ink-600 mb-4">Upload a CSV or XLSX file to add a new supplier. The pipeline will automatically run and update the database.</p>
            
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-4">
              <div>
                <label className="block text-sm font-medium mb-1">Supplier Name</label>
                <input 
                  type="text" 
                  value={uploadSupplier}
                  onChange={e => setUploadSupplier(e.target.value)}
                  placeholder="e.g. agoda, expedia"
                  className="w-full border border-ink-300 rounded p-2 text-sm" 
                />
              </div>
              <div>
                <label className="block text-sm font-medium mb-1">Data Type</label>
                <select 
                  value={uploadType} 
                  onChange={e => setUploadType(e.target.value as "hotels" | "rooms")}
                  className="w-full border border-ink-300 rounded p-2 text-sm"
                >
                  <option value="hotels">Hotels</option>
                  <option value="rooms">Rooms</option>
                </select>
              </div>
            </div>
            
            <div>
              <label className="block text-sm font-medium mb-1">Select File (CSV/XLSX)</label>
              <input type="file" accept=".csv,.xlsx" onChange={handleFileUpload} className="w-full text-sm border p-2 rounded" />
            </div>
          </div>
        </div>

        <div className="bg-white p-6 rounded shadow-sm border border-ink-200 flex flex-col h-fit">
          <h2 className="text-xl font-semibold mb-4">Pipeline Execution</h2>
          <p className="text-ink-600 text-sm mb-4">
            The pipeline resolves hotels across all uploaded files to generate the canonical database.
          </p>
          <div className="bg-ink-50 p-4 rounded font-mono text-sm mb-6 border border-ink-200">
            Status: {isPipelineRunning ? <span className="text-blue-600 font-bold">⏳ RUNNING</span> : <span className="text-green-600 font-bold">✅ IDLE</span>}<br/>
            Message: <span className="text-ink-600">{pipelineMessage}</span>
          </div>
          
          <button 
            onClick={() => {
              if (confirm("Run the pipeline manually?")) {
                handleRunPipeline();
              }
            }}
            disabled={isPipelineRunning}
            className={`w-full py-3 rounded font-bold text-white transition mt-auto ${
              isPipelineRunning ? 'bg-ink-400 cursor-not-allowed' : 'bg-blue-600 hover:bg-blue-700'
            }`}
          >
            {isPipelineRunning ? "Pipeline Running..." : "Run Pipeline Manually"}
          </button>
        </div>
      </div>
    </div>
  );
}
