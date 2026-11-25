"use client";

import { useRef, useState } from "react";
import { Button } from "@/design-system/components/Button";
import { Modal } from "@/design-system/components/Modal";
import { useToast } from "@/design-system/components/Toast";
import { FormAlert } from "@/features/auth/components/FormAlert";
import type { DocumentOut } from "@/lib/api/types";
import { useDeleteDocument } from "../hooks";
import { documentActionError } from "../messages";
import { FIGMA, PROVISIONAL } from "../strings";

/** Destructive Modal for one file (gate GF0B-21). Starts on Cancel; deletion is claimed only after the backend's 204. */
export function DeleteDocumentModal({ courseId, document, onClose, onDeleted }: {
  courseId: string;
  document: Pick<DocumentOut, "id" | "file_name"> | null;
  onClose: () => void;
  onDeleted?: (documentId: string) => void;
}) {
  const cancel = useRef<HTMLButtonElement>(null);
  const mutation = useDeleteDocument(courseId);
  const toast = useToast();
  const [error, setError] = useState<string | null>(null);
  const close = () => {
    setError(null);
    onClose();
  };
  return (
    <Modal
      open={document !== null}
      onClose={close}
      busy={mutation.isPending}
      initialFocus={cancel}
      title={PROVISIONAL.deleteFileTitle}
      description={document ? PROVISIONAL.deleteFileBody(document.file_name) : undefined}
      footer={
        <>
          <Button ref={cancel} variant="secondary" onClick={close} disabled={mutation.isPending}>
            {FIGMA.cancel}
          </Button>
          <Button
            variant="danger"
            loading={mutation.isPending}
            onClick={() => {
              if (!document || mutation.isPending) return;
              setError(null);
              mutation.mutate(document.id, {
                onSuccess: (id) => {
                  toast(PROVISIONAL.fileDeleted, "success");
                  setError(null);
                  onDeleted?.(id);
                  onClose();
                },
                onError: (e) => setError(documentActionError(e)),
              });
            }}
          >
            {PROVISIONAL.deleteFile}
          </Button>
        </>
      }
    >
      <FormAlert message={error} />
    </Modal>
  );
}
