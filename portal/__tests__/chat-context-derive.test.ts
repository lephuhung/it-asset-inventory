import { describe, it, expect, vi, beforeEach } from "vitest";

import {
  deriveMachineId,
  OPEN_STORAGE_KEY,
  readStoredOpen,
  writeStoredOpen,
} from "@/components/chat/use-chat-panel";

const UUID = "11111111-1111-4111-8111-111111111111";

function fakeStorage(): Storage {
  const map = new Map<string, string>();
  return {
    get length() {
      return map.size;
    },
    clear: () => map.clear(),
    getItem: (k: string) => map.get(k) ?? null,
    key: (i: number) => Array.from(map.keys())[i] ?? null,
    removeItem: (k: string) => void map.delete(k),
    setItem: (k: string, v: string) => void map.set(k, v),
  } as Storage;
}

describe("deriveMachineId", () => {
  it("extracts the id on the machine detail route", () => {
    expect(deriveMachineId(`/machines/${UUID}`)).toBe(UUID);
  });

  it("returns null elsewhere", () => {
    expect(deriveMachineId("/dashboard")).toBeNull();
    expect(deriveMachineId("/machines")).toBeNull();
    expect(deriveMachineId("/machines/")).toBeNull();
    expect(deriveMachineId("/")).toBeNull();
    expect(deriveMachineId("")).toBeNull();
  });

  it("rejects a non-uuid segment instead of leaking a garbage id", () => {
    expect(deriveMachineId("/machines/not-a-uuid")).toBeNull();
    expect(deriveMachineId("/machines/12345")).toBeNull();
  });

  it("rejects deeper paths under the machine route", () => {
    expect(deriveMachineId(`/machines/${UUID}/edit`)).toBeNull();
    expect(deriveMachineId(`/machines/${UUID}/software`)).toBeNull();
  });

  it("accepts upper-case uuid hex", () => {
    expect(deriveMachineId(`/machines/${UUID.toUpperCase()}`)).toBe(UUID.toUpperCase());
  });

  it("ignores a query string or hash", () => {
    expect(deriveMachineId(`/machines/${UUID}?tab=software`)).toBe(UUID);
    expect(deriveMachineId(`/machines/${UUID}#top`)).toBe(UUID);
  });

  it("does not match a route that merely starts with /machines", () => {
    expect(deriveMachineId(`/machines-archive/${UUID}`)).toBeNull();
  });

  it("ignores a trailing slash", () => {
    expect(deriveMachineId(`/machines/${UUID}/`)).toBe(UUID);
  });

  it("accepts any well-formed uuid version (backend is the source of truth)", () => {
    expect(deriveMachineId("/machines/11111111-1111-1111-8111-111111111111")).toBe(
      "11111111-1111-1111-8111-111111111111",
    );
  });
});

describe("rail open state persistence", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("defaults to closed when nothing is stored", () => {
    expect(readStoredOpen(fakeStorage())).toBe(false);
  });

  it("round-trips the open state", () => {
    const store = fakeStorage();
    writeStoredOpen(store, true);
    expect(readStoredOpen(store)).toBe(true);
    writeStoredOpen(store, false);
    expect(readStoredOpen(store)).toBe(false);
  });

  it("ignores junk in storage instead of throwing", () => {
    const store = fakeStorage();
    store.setItem(OPEN_STORAGE_KEY, "banana");
    expect(readStoredOpen(store)).toBe(false);
  });

  it("survives a storage that throws (private mode / SSR guard)", () => {
    const hostile = {
      getItem: () => {
        throw new Error("denied");
      },
      setItem: () => {
        throw new Error("denied");
      },
    } as unknown as Storage;

    expect(readStoredOpen(hostile)).toBe(false);
    expect(() => writeStoredOpen(hostile, true)).not.toThrow();
  });

  it("uses a stable storage key", () => {
    expect(OPEN_STORAGE_KEY).toBe("chat-rail-open");
  });
});