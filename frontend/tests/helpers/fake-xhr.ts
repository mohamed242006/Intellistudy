/**
 * A scripted XMLHttpRequest for upload tests (lib/api/upload.ts). Each request is recorded; the test drives it with
 * progress(), respond(), fail() or lets abort() run. Only the members upload.ts uses exist.
 */
import { vi } from "vitest";

export class FakeXHR {
  static all: FakeXHR[] = [];
  method = "";
  url = "";
  headers: Record<string, string> = {};
  body: FormData | null = null;
  withCredentials = true;
  responseType = "";
  status = 0;
  responseText = "";
  aborted = false;
  private responseHeaders: Record<string, string> = {};
  upload: { onprogress: ((event: { lengthComputable: boolean; loaded: number; total: number }) => void) | null } = { onprogress: null };
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onabort: (() => void) | null = null;

  constructor() {
    FakeXHR.all.push(this);
  }
  open(method: string, url: string) {
    this.method = method;
    this.url = url;
  }
  setRequestHeader(name: string, value: string) {
    this.headers[name] = value;
  }
  send(body: FormData) {
    this.body = body;
  }
  getResponseHeader(name: string): string | null {
    return this.responseHeaders[name.toLowerCase()] ?? null;
  }
  abort() {
    this.aborted = true;
    this.onabort?.();
  }
  /** The file sent in the `files` part. */
  get file(): File {
    return this.body?.get("files") as File;
  }
  progress(loaded: number, total: number) {
    this.upload.onprogress?.({ lengthComputable: true, loaded, total });
  }
  respond(status: number, body: unknown, headers: Record<string, string> = {}) {
    this.status = status;
    this.responseText = body === undefined ? "" : JSON.stringify(body);
    this.responseHeaders = Object.fromEntries(Object.entries(headers).map(([k, v]) => [k.toLowerCase(), v]));
    this.onload?.();
  }
  fail() {
    this.onerror?.();
  }
}

export function installFakeXHR() {
  FakeXHR.all = [];
  vi.stubGlobal("XMLHttpRequest", FakeXHR);
  return FakeXHR;
}

/** The last request whose file has this name. */
export function xhrFor(name: string): FakeXHR | undefined {
  return [...FakeXHR.all].reverse().find((xhr) => xhr.file?.name === name);
}
