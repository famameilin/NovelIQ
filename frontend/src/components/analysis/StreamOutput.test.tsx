import {act, render, screen} from "@testing-library/react";
import {beforeEach, expect, it} from "vitest";
import {StreamOutput} from "./StreamOutput";
import {useStreamStore} from "@/store/streamStore";
beforeEach(()=>{useStreamStore.getState().reset();useStreamStore.getState().setTaskId("task");});
it("没有进度字段也能展示实际模型输出",()=>{act(()=>useStreamStore.getState().appendLLMOutput({action:"output",invocation_id:"agent",stream_id:"stream",content:"实际模型文本",message:""}));render(<StreamOutput taskId="task"/>);expect(screen.getByText("实际模型文本")).toBeInTheDocument();});
it("尚无模型通信时展示等待状态",()=>{render(<StreamOutput taskId="task"/>);expect(screen.getByText("等待模型输出")).toBeInTheDocument();});
