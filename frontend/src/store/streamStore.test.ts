import {beforeEach, describe, expect, it} from "vitest";
import {useStreamStore} from "./streamStore";
import type {StreamEventData} from "@/api/streamTypes";
const event = (extra: Partial<StreamEventData> = {}): StreamEventData => ({action:"output", content:"正文", message:"", stream_id:"stream", invocation_id:"agent", ...extra});
beforeEach(() => useStreamStore.getState().reset());
describe("任务状态与模型通信", () => {
  it("状态不派生运行进度", () => { const store=useStreamStore.getState(); store.setStatus("running"); expect(useStreamStore.getState().status).toBe("running"); expect(useStreamStore.getState()).not.toHaveProperty("progress"); });
  it("不同 Agent 与模型流互相隔离", () => { const store=useStreamStore.getState();store.appendLLMOutput(event());store.appendLLMOutput(event({invocation_id:"other",content:"另一份"}));expect([...useStreamStore.getState().llmOutputs.values()].map(g=>g.outputText)).toEqual(["正文","另一份"]); });
  it("同一真实流连续追加", () => { const store=useStreamStore.getState();store.appendLLMOutput(event());store.appendLLMOutput(event({content:"继续"}));expect(useStreamStore.getState().llmOutputs.get("agent:stream")?.outputText).toBe("正文继续"); });
  it("切换任务清空通信缓冲", () => {const store=useStreamStore.getState();store.setTaskId("one");store.appendLLMOutput(event());store.setTaskId("two");expect(useStreamStore.getState().llmOutputs.size).toBe(0);});
  it("缺少真实 Agent 拒绝通信", () => {expect(()=>useStreamStore.getState().appendLLMOutput(event({invocation_id:null}))).toThrow("真实 Agent");});
});
