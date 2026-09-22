import { describe, expect, it } from "vitest";

import { parseSseChunk } from "./sseClient";

describe("parseSseChunk", () => {
  it("parses complete frames and keeps the partial tail", () => {
    const { frames, rest } = parseSseChunk(
      'id: evt_1\nevent: run.started\ndata: {"a":1}\n\nid: evt_2\nevent: phase.changed\ndata: {"b":2}\n\nid: evt_3\ndata: {"c"',
    );
    expect(frames).toHaveLength(2);
    expect(frames[0]).toMatchObject({ id: "evt_1", event: "run.started", data: '{"a":1}' });
    expect(rest).toContain('{"c"');
  });

  it("ignores frames without data", () => {
    const { frames } = parseSseChunk(": keepalive\n\n");
    expect(frames).toHaveLength(0);
  });
});
