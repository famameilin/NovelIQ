import {render, screen, waitFor} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type {ReactNode} from 'react';
import {QueryClient, QueryClientProvider} from '@tanstack/react-query';
import {MemoryRouter, Route, Routes, useLocation} from 'react-router-dom';
import {beforeEach, expect, it, vi} from 'vitest';
import {AnalysisTaskPage} from './AnalysisTaskPage';
import {useNovelStore} from '@/store/novelStore';
import {useStreamStore} from '@/store/streamStore';

const api=vi.hoisted(()=>({cancel:vi.fn(),resume:vi.fn(),status:vi.fn(),refetch:vi.fn(),
  state:'running',synced:false,error:null as unknown}));
vi.mock('@/api/analysis',()=>({cancelAnalysisTask:api.cancel,resumeAnalysisTask:api.resume}));
vi.mock('@/api/novels',()=>({getNovel:async()=>({title:'测试小说'})}));
vi.mock('@/hooks/useAnalysisStatus',()=>({useAnalysisStatus:(novel:string,task:string)=>{
  api.status(novel,task);
  return {status:api.state,projectionSynced:api.synced,query:{isError:!!api.error,error:api.error,refetch:api.refetch}};
}}));
vi.mock('sonner',()=>({toast:{info:vi.fn(),success:vi.fn(),error:vi.fn()}}));
vi.mock('@/components/layout/PageContainer',()=>({PageContainer:({children}:{children:ReactNode})=><main>{children}</main>}));
vi.mock('@/components/analysis/AnalysisProgressPanel',()=>({AnalysisProgressPanel:
  ({taskId,onCancel,onResume}:{taskId:string;onCancel:()=>void;onResume:()=>void})=><section aria-label="任务工作台">
    <p>{taskId}</p><button onClick={onCancel}>停止分析</button><button onClick={onResume}>恢复分析</button>
  </section>}));

function Location(){const location=useLocation();return <output aria-label="页面地址">{location.pathname+location.search}</output>;}
function View({client}:{client:QueryClient}){
  return <QueryClientProvider client={client}><MemoryRouter initialEntries={['/novels/novel/analysis/task']}>
    <Location /><Routes>
      <Route path="/novels/:novelId/analysis/:taskId" element={<AnalysisTaskPage />} />
      <Route path="/novels/:novelId" element={<p>小说详情与结果</p>} />
    </Routes>
  </MemoryRouter></QueryClientProvider>;
}
const client=()=>new QueryClient({defaultOptions:{queries:{retry:false}}});
beforeEach(()=>{
  vi.clearAllMocks();api.state='running';api.synced=false;api.error=null;
  api.cancel.mockResolvedValue({});api.resume.mockResolvedValue({task_id:'task'});
  useNovelStore.getState().clear();useStreamStore.getState().reset();
});

it('直接打开以 URL 任务为准，重取快照并同步小说作用域',async()=>{
  useNovelStore.setState({currentNovelId:'other-novel',currentTaskId:'other-task'});
  useStreamStore.getState().setTaskId('other-task');
  useStreamStore.getState().applyNotice('other-task','llm_output',{invocation_id:'foreign-agent',content:'旧小说内容'},1);
  useStreamStore.setState({snapshotReady:true});
  render(<View client={client()} />);
  expect(await screen.findByRole('heading',{name:'测试小说 · 分析任务详情'})).toBeVisible();
  expect(api.status).toHaveBeenCalledWith('novel','task');
  expect(api.status).not.toHaveBeenCalledWith('novel','other-task');
  expect(useNovelStore.getState().currentTaskId).toBe('task');
  expect(useStreamStore.getState().snapshotReady).toBe(false);
  expect(useStreamStore.getState().projection.executions).toEqual({});
  expect(screen.queryByRole('button',{name:/返回/})).toBeNull();
});

it('停止和恢复使用正式任务入口，恢复后留在相同任务详情',async()=>{
  const queryClient=client(),invalidate=vi.spyOn(queryClient,'invalidateQueries');
  render(<View client={queryClient} />);
  await userEvent.click(screen.getByRole('button',{name:'停止分析'}));
  expect(api.cancel).toHaveBeenCalledWith('novel','task');
  await userEvent.click(screen.getByRole('button',{name:'恢复分析'}));
  expect(api.resume).toHaveBeenCalledWith('novel','task');
  expect(invalidate).toHaveBeenCalledWith({queryKey:['task-status','novel','task']});
  expect(screen.getByLabelText('页面地址')).toHaveTextContent('/novels/novel/analysis/task');
});

it('完成后等待通知同步，随后自动进入同一任务结果',async()=>{
  api.state='completed';const queryClient=client();const view=render(<View client={queryClient} />);
  expect(screen.queryByRole('button',{name:'查看分析结果'})).toBeNull();
  expect(screen.queryByRole('button',{name:/返回/})).toBeNull();
  expect(screen.getByRole('region',{name:'任务工作台'})).toBeVisible();
  api.synced=true;view.rerender(<View client={queryClient} />);
  await waitFor(()=>expect(screen.getByLabelText('页面地址')).toHaveTextContent('/novels/novel?task_id=task'));
  expect(screen.getByText('小说详情与结果')).toBeVisible();
});

it('不存在或不属于当前小说的任务有独立错误和重试入口',async()=>{
  api.error={isAxiosError:true,response:{status:404}};
  render(<View client={client()} />);
  expect(screen.getByRole('alert')).toHaveTextContent('分析任务不存在或不属于当前小说');
  expect(screen.queryByRole('region',{name:'任务工作台'})).toBeNull();
  await userEvent.click(screen.getByRole('button',{name:'重试'}));
  await waitFor(()=>expect(api.refetch).toHaveBeenCalledOnce());
});
