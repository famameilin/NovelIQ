import { expect, it } from "vitest";
import { organizationConnections } from "./organizationConnections";

it("相同端点合并所有关系类型，反向关系保留独立方向", () => {
  expect(organizationConnections([
    { source_id: "a", target_id: "b", kind: "local_parent" },
    { source_id: "a", target_id: "b", kind: "causal" },
    { source_id: "a", target_id: "b", kind: "causal" },
    { source_id: "b", target_id: "a", kind: "reference" },
  ])).toEqual([
    { source_id: "a", target_id: "b", kinds: ["local_parent", "causal"] },
    { source_id: "b", target_id: "a", kinds: ["reference"] },
  ]);
});
