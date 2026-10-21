import {beforeEach, expect, it} from 'vitest';
import {render, screen} from '@testing-library/react';
import {AnalysisWorkbench} from './AnalysisWorkbench';
import {emptyAnalysisProjection} from '@/store/analysisProjection';
import {useStreamStore} from '@/store/streamStore';

beforeEach(()=>useStreamStore.getState().reset());

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
