import asyncio
import io
import os
import secrets
import sys
from pathlib import Path

import pandas as pd
from fastapi import APIRouter, File, Form, HTTPException, UploadFile

router = APIRouter(prefix="/admin", tags=["admin"])

PROJECT_ROOT = Path(__file__).parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"

# Global variable to track pipeline status
_pipeline_task: asyncio.Task | None = None





async def _run_pipeline_background():
    global _pipeline_task
    try:
        # Run the pipeline as a subprocess to avoid blocking the event loop
        # and to cleanly reuse the existing batch entry-point.
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "pipeline.run", "--force",
            cwd=str(PROJECT_ROOT),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )

        stdout, _ = await proc.communicate()
        if proc.returncode != 0:
            print(f"[admin] Pipeline failed with return code {proc.returncode}")
            print(stdout.decode())
        else:
            print("[admin] Pipeline completed successfully")
    except Exception as e:
        print(f"[admin] Pipeline error: {e}")


@router.get("/verify")
async def verify():
    """Check whether the admin panel is accessible."""
    return {"status": "ok"}


@router.get("/files")
async def list_files():
    """List all currently staged data files in the data directory."""
    files = []
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    for p in DATA_DIR.glob("*.csv"):
        if p.name.endswith("_hotels.csv") or p.name.endswith("_rooms.csv"):
            stat = p.stat()
            files.append({
                "filename": p.name,
                "size_kb": round(stat.st_size / 1024, 1),
            })
    return {"files": files}


@router.delete("/files/{filename}")
async def delete_file(filename: str):
    """Delete a staged data file."""
    if not filename.endswith(".csv") or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")

    file_path = DATA_DIR / filename
    if file_path.exists():
        file_path.unlink()
        return {"status": "success", "message": f"Deleted {filename}"}
    raise HTTPException(status_code=404, detail="File not found")


@router.post("/upload-supplier")
async def upload_supplier(
    file: UploadFile = File(...),
    supplier_name: str = Form(..., description="E.g., 'expedia' or 'booking'"),
    data_type: str = Form(..., description="'hotels' or 'rooms'"),
):
    """Uploads a supplier CSV/XLSX and saves it as a normalized CSV."""
    if not (file.filename.endswith(".csv") or file.filename.endswith(".xlsx")):
        raise HTTPException(status_code=400, detail="Only CSV or XLSX files are allowed")

    if data_type not in ["hotels", "rooms"]:
        raise HTTPException(status_code=400, detail="data_type must be 'hotels' or 'rooms'")

    safe_supplier = "".join(c for c in supplier_name if c.isalnum() or c in ("-", "_")).lower()
    if not safe_supplier:
        raise HTTPException(status_code=400, detail="supplier_name must contain at least one alphanumeric character")

    # Standardized as {supplier}_hotels.csv / {supplier}_rooms.csv so the
    # pipeline can recover the supplier name straight from the filename.
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    final_filename = f"{safe_supplier}_{data_type}.csv"
    save_path = DATA_DIR / final_filename

    try:
        contents = await file.read()

        if file.filename.endswith(".xlsx"):
            df = pd.read_excel(io.BytesIO(contents))
            df.to_csv(save_path, index=False)
        else:
            save_path.write_bytes(contents)

        return {"status": "success", "message": f"Saved {final_filename} successfully."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/trigger-pipeline")
async def trigger_pipeline():
    """Triggers the data cleaning and matching pipeline asynchronously."""
    global _pipeline_task

    if _pipeline_task and not _pipeline_task.done():
        raise HTTPException(status_code=409, detail="Pipeline is already running")

    _pipeline_task = asyncio.create_task(_run_pipeline_background())

    return {"status": "success", "message": "Pipeline triggered successfully"}


@router.get("/pipeline-status")
async def pipeline_status():
    """Check the status of the background pipeline."""
    global _pipeline_task

    if _pipeline_task is None:
        return {"status": "idle", "message": "No pipeline task has been run"}

    if not _pipeline_task.done():
        return {"status": "running", "message": "Pipeline is currently processing"}

    if _pipeline_task.exception():
        return {"status": "error", "message": f"Pipeline failed: {_pipeline_task.exception()}"}

    return {"status": "completed", "message": "Pipeline finished successfully"}
