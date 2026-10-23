import {expect,it} from 'vitest';
import {failureNotice} from './failureNotice';

const quota = "Error code: 429 - {'error': {'code': 'AccountQuotaExceeded', 'message': 'You have exceeded the 5-hour usage quota. It will reset at 2026-10-22 14:08:56 +0800 CST. We recommend upgrading your plan for more quota, or waiting for the reset.', 'param': '', 'type': 'TooManyRequests'}}";

it('把模型配额错误整理成一句摘要并保留原始内容',()=>{
  const notice=failureNotice(quota);
  expect(notice?.title).toBe("模型服务配额不足或请求受限（HTTP 429）：用量配额已用尽，将于 2026-10-22 14:08:56 +0800 CST 重置，恢复分析前需等待额度恢复。");
  expect(notice?.detail).toBe(quota);
});

it('非配额错误只保留通用摘要',()=>{
  expect(failureNotice('Error code: 500 - {"error": {"message": "boom"}}')?.title).toBe('模型服务内部错误（HTTP 500）。');
});

it('非 HTTP 错误保留首行原文',()=>{
  const notice=failureNotice('RuntimeError: 案例会话回合已耗尽');
  expect(notice?.title).toBe('RuntimeError: 案例会话回合已耗尽。');
  expect(notice?.detail).toBeUndefined();
});

it('空原因不产生告警',()=>{
  expect(failureNotice('')).toBeNull();
  expect(failureNotice(null)).toBeNull();
});
