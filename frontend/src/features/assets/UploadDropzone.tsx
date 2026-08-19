import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AnimatePresence, motion } from "motion/react";
import { Loader2, UploadCloud } from "lucide-react";
import { type ChangeEvent, type DragEvent, useRef, useState } from "react";

import { messageFor } from "@/lib/api-error";
import { fadeIn } from "@/lib/motion";
import { cn } from "@/lib/utils";
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

  const uploading = uploadMutation.isPending;

  return (
    <div className="flex flex-col gap-2">
      {/* No role/tabIndex/onClick on this wrapper: a native file input
       * nested inside a role="button" element is a real nested-interactive
       * violation (confirmed live with axe-core -- a negative tabindex or
       * aria-hidden on the input doesn't fix it, since assistive tech can
       * still reach it). The `<label>` below is the single interactive
       * control; the input keeps native keyboard/click behavior for free. */}
      <motion.div
        onDragOver={(event) => {
          event.preventDefault();
          setIsDragging(true);
        }}
        onDragLeave={() => setIsDragging(false)}
        onDrop={handleDrop}
        animate={{ scale: isDragging ? 1.01 : 1 }}
        transition={{ duration: 0.15 }}
        className={cn(
          "relative overflow-hidden rounded-xl border-2 border-dashed transition-colors duration-200",
          isDragging
            ? "border-primary bg-accent/40"
            : uploading
              ? "border-ai/50 bg-ai-soft/40"
              : "border-border bg-sunken/60 hover:border-border-strong",
        )}
      >
        <label
          htmlFor="document-upload-input"
          className="flex cursor-pointer flex-col items-center justify-center gap-3 p-8 text-center"
        >
          <AnimatePresence mode="wait" initial={false}>
            <motion.div
              key={uploading ? "uploading" : "idle"}
              variants={fadeIn}
              initial="hidden"
              animate="visible"
              exit="hidden"
              className="flex flex-col items-center gap-3"
            >
              <div
                className={cn(
                  "flex h-12 w-12 items-center justify-center rounded-xl",
                  uploading ? "bg-ai text-ai-foreground" : "bg-card text-muted-foreground shadow-subtle",
                )}
              >
                {uploading ? (
                  <Loader2 className="h-5 w-5 animate-spin" />
                ) : (
                  <UploadCloud className="h-5 w-5" />
                )}
              </div>
              <div>
                <p className="text-sm font-medium">
                  {uploading ? "Uploading document…" : "Drag & drop, or choose a file"}
                </p>
                <p className="mt-1 text-xs text-muted-foreground">
                  {uploading
                    ? "Extraction, understanding and embedding begin automatically"
                    : `Supported formats: ${SUPPORTED_EXTENSIONS.join(", ")}`}
                </p>
              </div>
            </motion.div>
          </AnimatePresence>
        </label>
        <input
          id="document-upload-input"
          ref={inputRef}
          type="file"
          accept={SUPPORTED_EXTENSIONS.join(",")}
          className="sr-only"
          onChange={handleChange}
        />
      </motion.div>

      {uploadMutation.isError && (
        <p role="alert" className="text-sm text-destructive">
          {messageFor(uploadMutation.error)}
        </p>
      )}
    </div>
  );
}
