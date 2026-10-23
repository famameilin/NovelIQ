import {beforeEach, expect, it} from 'vitest';
import {render, screen} from '@testing-library/react';
import {AnalysisWorkbench} from './AnalysisWorkbench';
import {emptyAnalysisProjection} from '@/store/analysisProjection';
import {useStreamStore} from '@/store/streamStore';

beforeEach(()=>useStreamStore.getState().reset());

const quota = "Error code: 429 - {'error': {'code': 'AccountQuotaExceeded', 'message': 'You have exceeded the 5-hour usage quota. It will reset at 2026-10-22 14:08:56 +0800 CST.', 'param': '', 'type': 'TooManyRequests'}}";

it.each(['cancelled','failed'] as const)('阶段 %s 后不把缺失收尾记录显示成仍在训练',status=>{
  const projection={...emptyAnalysisProjection(),stage:'topic-model',status,
    stages:{'topic-model':{stage:'topic-model',status,steps:{'主题训练':{status:'running'}}}}};
  useStreamStore.setState({projection,status,snapshotReady:true});
  render(<AnalysisWorkbench taskId="task" onCancel={()=>{}} onResume={()=>{}} />);
  expect(screen.queryByText('执行中')).toBeNull();
  expect(screen.getAllByText(status==='cancelled'?'已停止 · 完成状态未记录':'已中断 · 完成状态未记录')).toHaveLength(1);
  expect(screen.getByText('细分进度未记录')).toBeVisible();
  expect(screen.getByRole('button',{name:'恢复分析'})).toBeEnabled();
});

it('失败原因显示为摘要，原始错误折叠保留',()=>{
  const projection={...emptyAnalysisProjection(),stage:'annotate',status:'failed' as const,error:quota};
  useStreamStore.setState({projection,status:'failed',snapshotReady:true});
  render(<AnalysisWorkbench taskId="task" onCancel={()=>{}} onResume={()=>{}} />);
  expect(screen.getByText(/模型服务配额不足或请求受限（HTTP 429）/)).toBeVisible();
  expect(screen.getByText(/AccountQuotaExceeded/).closest('details')?.open).toBe(false);
  expect(screen.getByText('查看原始错误')).toBeVisible();
});

it('失败后尚未开始的阶段显示未执行',()=>{
  const projection={...emptyAnalysisProjection(),stage:'annotate',status:'failed' as const,
    stages:{annotate:{stage:'annotate',status:'failed',steps:{confirmed_chapters:{current:3,total:26,unit:'章'}}},linguistic:{stage:'linguistic',status:'pending'}}};
  useStreamStore.setState({projection,status:'failed',snapshotReady:true});
  render(<AnalysisWorkbench taskId="task" onCancel={()=>{}} onResume={()=>{}} />);
  expect(screen.queryByText('等待执行')).toBeNull();
  expect(screen.getAllByText('未执行')).toHaveLength(2);
});

