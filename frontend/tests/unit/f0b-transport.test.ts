import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { downloadDocument } from "@/features/documents/api";
import { OBJECT_URL_TTL_MS, saveBlob } from "@/features/documents/hooks";
import { onSessionExpired } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import { UPLOAD_FIELD, UploadAbortedError, uploadFile } from "@/lib/api/upload";
import { tokenStore } from "@/lib/auth/token-store";
import { doc } from "../helpers/data";
import { fakeBackend, json, problem, TOKEN } from "../helpers/fake-backend";
import { FakeXHR, installFakeXHR } from "../helpers/fake-xhr";

const flush = () => new Promise((resolve) => setTimeout(resolve, 0));
const pdf = () => new File(["%PDF-1.4"], "lecture.pdf", { type: "application/pdf" });

beforeEach(() => {
  tokenStore.clear();
  tokenStore.set("access-token-1", 900);
});

afterEach(() => tokenStore.clear());

describe("GF0B-15 one request per file with progress", () => {
  it("GF0B-15 sends one multipart file part named `files` with the bearer token, no cookies, and reports progress", async () => {
    installFakeXHR();
    const progress: number[] = [];
    const done = uploadFile("c-1", pdf(), ({ loaded, total }) => progress.push(Math.round((loaded / total) * 100)));
    const xhr = FakeXHR.all[0]!;
    expect(xhr.method).toBe("POST");
    expect(xhr.url).toBe("/api/v1/courses/c-1/documents");
    expect(xhr.headers.Authorization).toBe("Bearer access-token-1");
    expect(xhr.withCredentials).toBe(false);
    expect(UPLOAD_FIELD).toBe("files");
    expect((xhr.body!.getAll("files") as File[]).map((f) => f.name)).toEqual(["lecture.pdf"]);
    xhr.progress(25, 100);
    xhr.progress(100, 100);
    const accepted = doc({ status: "queued" });
    xhr.respond(202, { documents: [{ ...accepted, duplicate: false }] });
    expect((await done).documents[0]!.id).toBe(accepted.id);
    expect(progress).toEqual([25, 100]);
  });

  it("GF0B-15 a rejected file becomes a typed error with its reason code", async () => {
    installFakeXHR();
    const done = uploadFile("c-1", pdf(), () => {});
    FakeXHR.all[0]!.respond(422, { type: "about:blank#upload_rejected", detail: "Some files were rejected.", files: [{ file: "lecture.pdf", reason: "type_mismatch", message: "x" }] });
    const error = await done.catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).files).toEqual([{ file: "lecture.pdf", reason: "type_mismatch" }]);
  });

  it("GF0B-16 aborting a transfer rejects with UploadAbortedError; a network failure with a network error", async () => {
    installFakeXHR();
    const controller = new AbortController();
    const aborted = uploadFile("c-1", pdf(), () => {}, controller.signal);
    controller.abort();
    await expect(aborted).rejects.toBeInstanceOf(UploadAbortedError);
    const failed = uploadFile("c-1", pdf(), () => {});
    FakeXHR.all[1]!.fail();
    await expect(failed).rejects.toMatchObject({ kind: "network" });
  });

  it("GF0B-16 a 429 carries Retry-After", async () => {
    installFakeXHR();
    const done = uploadFile("c-1", pdf(), () => {});
    FakeXHR.all[0]!.respond(429, { type: "about:blank#rate_limited" }, { "Retry-After": "90" });
    await expect(done).rejects.toMatchObject({ kind: "rate_limited", retryAfterSeconds: 90 });
  });
});

describe("GF0B-24 session expiry during an upload", () => {
  it("GF0B-24 a 401 triggers one refresh and one retry with the new token", async () => {
    installFakeXHR();
    const backend = fakeBackend().on("POST /auth/refresh", () => json(200, TOKEN(2)));
    const done = uploadFile("c-1", pdf(), () => {});
    FakeXHR.all[0]!.respond(401, { type: "about:blank#token_invalid" });
    await vi.waitFor(() => expect(FakeXHR.all).toHaveLength(2));
    expect(FakeXHR.all[1]!.headers.Authorization).toBe("Bearer access-token-2");
    FakeXHR.all[1]!.respond(202, { documents: [{ ...doc(), duplicate: false }] });
    await expect(done).resolves.toBeTruthy();
    expect(backend.count("POST /auth/refresh")).toBe(1);
  });

  it("GF0B-24 a failed refresh ends the session and reports expiry", async () => {
    installFakeXHR();
    fakeBackend().on("POST /auth/refresh", () => problem(401, "session_invalid"));
    const expired = vi.fn();
    const off = onSessionExpired(expired);
    const done = uploadFile("c-1", pdf(), () => {});
    FakeXHR.all[0]!.respond(401, {});
    await expect(done).rejects.toMatchObject({ kind: "session_expired" });
    expect(expired).toHaveBeenCalledOnce();
    expect(tokenStore.get()).toBeNull();
    off();
  });
});

describe("GF0B-22 download", () => {
  it("GF0B-22 fetches the file with the bearer token, reads the attachment name and accepts only attachments", async () => {
    const backend = fakeBackend().on("GET /documents/d-1/file", () =>
      new Response("%PDF", { status: 200, headers: { "content-disposition": "attachment; filename*=UTF-8''Lecture%201.pdf", "content-type": "application/pdf" } }),
    );
    const { blob, fileName } = await downloadDocument("d-1");
    expect(fileName).toBe("Lecture 1.pdf");
    expect(blob.size).toBe(4);
    expect(backend.calls[0]!.headers.Authorization).toBe("Bearer access-token-1");
    expect(backend.calls[0]!.credentials).toBe("omit");

    fakeBackend().on("GET /documents/d-2/file", () => new Response("<html>", { status: 200, headers: { "content-disposition": "inline" } }));
    await expect(downloadDocument("d-2")).rejects.toBeInstanceOf(ApiError);
    fakeBackend().on("GET /documents/d-3/file", () => problem(404, "not_found", "Resource not found."));
    await expect(downloadDocument("d-3")).rejects.toMatchObject({ kind: "not_found" });
  });

  it("GF0B-22 a 401 during download refreshes once and retries", async () => {
    let first = true;
    const backend = fakeBackend()
      .on("GET /documents/d-1/file", () => {
        if (first) {
          first = false;
          return problem(401, "token_invalid");
        }
        return new Response("x", { status: 200, headers: { "content-disposition": "attachment; filename*=UTF-8''a.pdf" } });
      })
      .on("POST /auth/refresh", () => json(200, TOKEN(5)));
    await expect(downloadDocument("d-1")).resolves.toMatchObject({ fileName: "a.pdf" });
    expect(backend.count("POST /auth/refresh")).toBe(1);
    expect(backend.calls.at(-1)!.headers.Authorization).toBe("Bearer access-token-5");
  });

  it("GF0B-22 the object URL is revoked after the download starts, and the anchor is removed", async () => {
    vi.useFakeTimers();
    try {
      const create = vi.fn(() => "blob:http://localhost/1");
      const revoke = vi.fn();
      vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: create, revokeObjectURL: revoke }));
      const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
      saveBlob(new Blob(["x"]), "<img src=x onerror=alert(1)>.pdf");
      expect(click).toHaveBeenCalledOnce();
      const anchor = click.mock.instances[0] as unknown as HTMLAnchorElement;
      expect(anchor.download).toBe("<img src=x onerror=alert(1)>.pdf");
      expect(anchor.isConnected).toBe(false);
      expect(document.querySelector("img")).toBeNull();
      expect(revoke).not.toHaveBeenCalled();
      vi.advanceTimersByTime(OBJECT_URL_TTL_MS);
      expect(revoke).toHaveBeenCalledWith("blob:http://localhost/1");
    } finally {
      vi.useRealTimers();
    }
    await flush();
  });
});
