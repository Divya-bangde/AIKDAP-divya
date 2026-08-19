import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Loader2, UploadCloud } from "lucide-react";
import { type ChangeEvent, type DragEvent, useRef, useState } from "react";

import { messageFor } from "@/lib/api-error";
import * as assetsService from "@/services/assets";

/** Formats accepted here match `_PLAIN_TEXT_MIME_TYPES` in
 * `backend/app/modules/assets/processing/extractors.py` exactly — the
 * only formats the backend can actually extract text from today.
 * Claiming PDF/DOCX support here would be a UI lie about a real
 * backend limitation. */
const SUPPORTED_EXTENSIONS = [".txt", ".csv", ".md", ".json"];

export function UploadDropzone({ projectId }: { projectId: string }) {
  const [isDragging, setIsDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const queryClient = useQueryClient();

  const uploadMutation = useMutation({
    mutationFn: (file: File) => assetsService.uploadAsset(projectId, file),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["assets", projectId] });
    },
  });

  function handleFiles(files: FileList | null) {
    const file = files?.[0];
    if (file) uploadMutation.mutate(file);
  }

  function handleDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setIsDragging(false);
    handleFiles(event.dataTransfer.files);
  }

  function handleChange(event: ChangeEvent<HTMLInputElement>) {
    handleFiles(event.target.files);
    event.target.value = "";
  }

  return (
    <div className="flex flex-col gap-2">
      <div
        onDragOver={(event) => {
          event.preventDefault();
          setIsDragging(true);
        }}
        onDragLeave={() => setIsDragging(false)}
        onDrop={handleDrop}
        onClick={() => inputRef.current?.click()}
        role="button"
        tabIndex={0}
        onKeyDown={(event) => {
          if (event.key === "Enter" || event.key === " ") inputRef.current?.click();
        }}
        aria-label="Upload research document"
        className={`flex cursor-pointer flex-col items-center justify-center gap-3 rounded-lg border-2 border-dashed p-10 text-center transition-colors ${
          isDragging ? "border-primary bg-accent/50" : "border-border hover:border-primary/50"
        }`}
      >
        {uploadMutation.isPending ? (
          <Loader2 className="h-8 w-8 animate-spin text-primary" />
        ) : (
          <UploadCloud className="h-8 w-8 text-muted-foreground" />
        )}
        <div>
          <p className="text-sm font-medium">
            {uploadMutation.isPending ? "Uploading…" : "Drag & drop, or choose a file"}
          </p>
          <p className="mt-1 text-xs text-muted-foreground">
            Supported formats: {SUPPORTED_EXTENSIONS.join(", ")}
          </p>
        </div>
        <input
          ref={inputRef}
          type="file"
          accept={SUPPORTED_EXTENSIONS.join(",")}
          className="sr-only"
          onChange={handleChange}
          aria-hidden="true"
        />
      </div>

      {uploadMutation.isError && (
        <p role="alert" className="text-sm text-destructive">
          {messageFor(uploadMutation.error)}
        </p>
      )}
    </div>
  );
}
