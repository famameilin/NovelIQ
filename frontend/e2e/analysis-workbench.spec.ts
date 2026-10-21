/** 分析工作台的桌面交互与视觉验收，接口完全由夹具提供 */
import {test,expect,type Page} from "@playwright/test";

const novel="workbench-fixture",task="task-workbench";
const stages=["preprocess","annotate","linguistic","aggregate","topic-model","diagnose"];
const snapshot=(stage="annotate",capacities=[20,30])=>{
 const models=capacities.map((capacity,i)=>({model_id:i===0?"Qwen3 · 章节分析模型":"DeepSeek · 全书诊断与长模型名称展示",capacity}));
 const seats=models.flatMap((model,m)=>Array.from({length:Math.min(6,model.capacity)},(_,slot)=>({
  model_id:model.model_id,slot,reservation_id:`seat-${m}-${slot}`,run_id:m?"":"run",work_id:m?"":"chapter-12",foreign:!!m,
 })));
 return {cursor:100,run_id:"run",task_id:task,status:"running",stage,error:null,sync_pending:false,models,seats,
 stages:Object.fromEntries(stages.map(key=>[key,{stage:key,status:key===stage?"running":stages.indexOf(key)<stages.indexOf(stage)?"completed":"pending",
 steps:key==="preprocess"?{"章节入库":{current:120,total:120,unit:"章",status:"completed"}}:key==="annotate"?{"confirmed_chapters":{current:12,total:120,unit:"章",status:"running"}}:
 key==="topic-model"?{"语料准备":{current:3200,total:3200,unit:"段落",status:"completed"},"主题训练":{status:"running"}}:{}}])),
 executions:{"agent-1":{invocation_id:"agent-1",work_id:"chapter-12",reservation_id:"seat-0-0",model_id:models[0].model_id,
 stage,sub_stage:"annotation",chapter_id:12,activity:"thinking",output:"正在整理本章的事件、角色与证据。",thinking:"检查原文，核实前后关系。",tools:{},truncated:false}}};
};
async function fixture(page:Page,stage="annotate",capacities=[20,30],options:{status?:string;deferSnapshot?:boolean}={}) {
 const data=snapshot(stage,capacities);
 data.status=options.status??"running";
 await page.addInitScript(({data,deferSnapshot})=>{
  class FixtureSource {
   static current:FixtureSource;onopen:(()=>void)|null=null;onerror:(()=>void)|null=null;
   handlers=new Map<string,(event:MessageEvent)=>void>();
   constructor(){FixtureSource.current=this;setTimeout(()=>{this.onopen?.();if(!deferSnapshot)this.emit("snapshot",data,data.cursor);},30);}
   addEventListener(type:string,handler:(event:MessageEvent)=>void){this.handlers.set(type,handler);}
   close(){}
   emit(type:string,data:unknown,seq?:number){this.handlers.get(type)?.({data:JSON.stringify(data),lastEventId:seq==null?"":String(seq)} as MessageEvent);}
  }
  Object.assign(window,{EventSource:FixtureSource,__notice:(type:string,data:unknown,seq?:number)=>FixtureSource.current.emit(type,data,seq)});
 },{data,deferSnapshot:options.deferSnapshot});
 await page.route("**/api/**",async route=>{
  const path=new URL(route.request().url()).pathname;
  if(!path.startsWith('/api/'))return route.continue();
  const record={novel_id:novel,task_id:task,status:data.status,created_at:"2026-10-21T08:00:00"};
  let value:unknown={};
  if(path.endsWith("/tasks"))value={novel_id:novel,tasks:[record]};
  else if(path.endsWith("/status"))value=record;
  else if(path.endsWith("/resume"))value={task_id:task,novel_id:novel};
  else if(path.endsWith("/tabs/dashboard"))value={run_id:"run",diagnosis:null,narrative_structure:{},character_stats:{},
   style_stats:{},chapter_metrics:{chapters:[],book:{}},topics:[],emotion_trend:[]};
  else if(path.endsWith(novel))value={novel_id:novel,title:"长篇小说 · 分析工作台",filename:"小说.txt",status:"running",file_size:12000,upload_time:"2026-10-21T08:00:00"};
  return route.fulfill({json:value});
 });
 await page.goto(`/novels/${novel}/analysis/${task}`);
 if(data.status==='completed'&&!options.deferSnapshot) {
  await expect(page.getByText('暂无诊断数据')).toBeVisible();
 } else {
  await expect(page.getByRole("region",{name:"分析工作台"})).toBeVisible();
  if(!options.deferSnapshot)await expect(page.getByText("正在读取执行快照…")).toHaveCount(0);
 }
 return data;
}
async function notice(page:Page,type:string,data:unknown,seq?:number) {
 await page.evaluate(({type,data,seq})=>(window as unknown as {__notice:(t:string,d:unknown,s?:number)=>void}).__notice(type,data,seq),{type,data,seq});
}
test("20 与 30 席、选择、离座保留、滚轮和主题",async({page},info)=>{
 await page.setViewportSize({width:1440,height:1050});
 const errors:string[]=[];page.on("pageerror",e=>errors.push(e.message));
 const data=await fixture(page);
 await expect(page.locator("[data-workstation]")).toHaveCount(50);
 const seat=page.getByRole("button",{name:/Qwen3.*工位 1 · 章节标注/});
 await seat.focus();await page.keyboard.press("Enter");
 await expect(page.getByText("正在整理本章的事件、角色与证据。")).toBeVisible();
 await page.screenshot({path:info.outputPath("workbench-50-overview.png"),fullPage:true});
 const canvas=page.getByRole("img",{name:"50 个模型容量工位"});
 const scene=canvas.locator(":scope > g"),before=await scene.getAttribute("transform");
 const box=(await canvas.boundingBox())!;
 await page.mouse.click(box.x+box.width*.5,box.y+box.height*.5);
 expect(await scene.getAttribute("transform")).toBe(before);
 await seat.focus();await page.keyboard.press("Enter");
 await page.mouse.move(box.x+box.width*.55,box.y+box.height*.5);await page.mouse.wheel(0,-250);
 await expect.poll(()=>scene.getAttribute("transform")).not.toBe(before);
 await notice(page,"capacity",{task_id:task,models:data.models,seats:[]},101);
 await expect(page.getByText("执行详情 · 已离座，详情保留")).toBeVisible();
 await expect(page.getByText("正在整理本章的事件、角色与证据。")).toBeVisible();
 await page.screenshot({path:info.outputPath("workbench-light.png"),fullPage:true});
 const lightBackground=await page.evaluate(()=>getComputedStyle(document.documentElement).getPropertyValue("--background"));
 await page.getByRole("button",{name:"切换深浅模式"}).click();
 await expect.poll(()=>page.evaluate(()=>getComputedStyle(document.documentElement).getPropertyValue("--background"))).not.toBe(lightBackground);
 await page.screenshot({path:info.outputPath("workbench-dark.png"),fullPage:true});
 expect(errors).toEqual([]);
});
for(const stage of ["preprocess","linguistic","aggregate","topic-model"]) {
 test(`${stage} 紧凑阶段无工位和缩放`,async({page})=>{
  await fixture(page,stage);
  await expect(page.locator("[data-analysis-stage]")).toHaveCount(6);
  await expect(page.locator("[data-workstation]")).toHaveCount(0);
  await expect(page.getByText(/滚轮缩放/)).toHaveCount(0);
 });
}
test("大量工位与异常恢复",async({page},info)=>{
 await page.setViewportSize({width:1440,height:1050});await fixture(page,"diagnose",[60,60]);
 await expect(page.locator("[data-workstation]")).toHaveCount(120);
 await page.screenshot({path:info.outputPath("workbench-120-overview.png"),fullPage:true});
 await notice(page,"agent_activity",{task_id:task,invocation_id:"agent-1",activity:"error",message:"此次执行调用失败"},101);
 await notice(page,"capacity",{task_id:task,models:snapshot("diagnose",[60,60]).models,seats:[]},102);
 await notice(page,"task_error",{task_id:task,status:"failed",error:"模型连接失败，执行记录已保留"},103);
 await page.getByRole("combobox",{name:"选择执行记录"}).selectOption("agent-1");
 await expect(page.getByText("执行详情 · 已离座，详情保留")).toBeVisible();
 await expect(page.getByText("此次执行调用失败")).toBeVisible();
 await expect(page.getByRole("button",{name:"恢复分析",exact:true})).toBeVisible();
 await page.screenshot({path:info.outputPath("workbench-120-failed.png"),fullPage:true});
});

test("少量工位与满载工位均按实际容量绘制",async({page},info)=>{
 await page.setViewportSize({width:1440,height:1050});await fixture(page,"annotate",[3,5]);
 await expect(page.locator("[data-workstation]")).toHaveCount(8);
 const full=snapshot("annotate",[20,30]);
 full.seats=full.models.flatMap((model,m)=>Array.from({length:model.capacity},(_,slot)=>({model_id:model.model_id,slot,
 reservation_id:`full-${m}-${slot}`,run_id:"run",work_id:`work-${slot}`,foreign:false})));
 full.executions=Object.fromEntries(full.seats.map((seat,i)=>[`agent-${i}`,{invocation_id:`agent-${i}`,work_id:seat.work_id,
 reservation_id:seat.reservation_id,model_id:seat.model_id,stage:"annotate",sub_stage:"annotation",chapter_id:i+1,
 activity:["thinking","generating","tool","saving"][i%4],output:"已记录输出",thinking:"已记录思考",tools:{},truncated:false}])) as typeof full.executions;
 await notice(page,"snapshot",{...full,cursor:200},200);
 await expect(page.locator("[data-workstation]")).toHaveCount(50);
 await expect(page.getByText("本任务 50 席 · 其他任务 0 席")).toBeVisible();
 await page.screenshot({path:info.outputPath("workbench-full-50.png"),fullPage:true});
});

test("任务选择器分流、直接地址和刷新，不设置返回按钮",async({page},info)=>{
 await page.setViewportSize({width:1440,height:1180});await fixture(page);
 await expect(page).toHaveURL(new RegExp(`/novels/${novel}/analysis/${task}$`));
 await expect(page.getByRole('link',{name:'仪表盘',exact:true})).toHaveCount(0);
 expect((await page.getByRole('main').boundingBox())!.x).toBeLessThan(2);
 await expect(page.getByRole('button',{name:/返回/})).toHaveCount(0);
 await page.getByRole('navigation',{name:'面包屑导航'}).getByRole('link',{name:'长篇小说 · 分析工作台',exact:true}).click();
 await expect(page).toHaveURL(new RegExp(`/novels/${novel}$`));
 await expect(page.getByRole('link',{name:'仪表盘',exact:true})).toBeVisible();
 await expect(page.getByRole('region',{name:'分析工作台'})).toHaveCount(0);
 await page.getByRole('button',{name:'选择任务',exact:true}).click();
 await page.getByText('task-wor',{exact:true}).click();
 await expect(page.getByRole('region',{name:'分析工作台'})).toBeVisible();
 await expect(page.getByRole('link',{name:'仪表盘',exact:true})).toHaveCount(0);
 await page.reload();
 await expect(page.locator('[data-workstation]')).toHaveCount(50);
 await expect(page.getByRole('link',{name:'仪表盘',exact:true})).toHaveCount(0);
 await expect(page.locator('[data-analysis-stage=diagnose]')).toBeInViewport();
 await expect(page.getByRole('navigation',{name:'面包屑导航'})).toContainText('分析任务详情');
 await page.goto(`/novels/${novel}?task_id=${task}`);
 await expect(page).toHaveURL(new RegExp(`/novels/${novel}/analysis/${task}$`));
 await expect(page.getByRole('button',{name:'查看分析任务',exact:true})).toHaveCount(0);
 await page.screenshot({path:info.outputPath('task-detail.png'),fullPage:true});
});

test("停止恢复后，完成且同步时自动进入结果并替换历史",async({page},info)=>{
 const data=await fixture(page);
 await page.getByRole('navigation',{name:'面包屑导航'}).getByRole('link',{name:'长篇小说 · 分析工作台',exact:true}).click();
 await page.getByRole('button',{name:'选择任务',exact:true}).click();
 await page.getByText('task-wor',{exact:true}).click();
 await expect(page.locator('[data-workstation]')).toHaveCount(50);
 const cancel=page.waitForRequest(request=>request.url().includes(`/tasks/${task}/cancel`)&&request.method()==='POST');
 await page.getByRole('button',{name:'停止分析',exact:true}).click();await cancel;
 await notice(page,'task_state',{task_id:task,status:'cancelling'},101);
 await expect(page.getByRole('button',{name:'正在停止',exact:true})).toBeDisabled();
 await notice(page,'task_cancelled',{task_id:task,status:'cancelled'},102);
 await expect(page.getByRole('button',{name:'恢复分析',exact:true})).toBeVisible();
 const resume=page.waitForRequest(request=>request.url().includes(`/tasks/${task}/resume`)&&request.method()==='POST');
 await page.getByRole('button',{name:'恢复分析',exact:true}).click();await resume;
 await expect(page.getByRole('button',{name:'停止分析',exact:true})).toBeVisible();
 await notice(page,'notification_status',{task_id:task,warning:null,sync_pending:true});
 data.status='completed';
 await notice(page,'task_complete',{task_id:task,status:'completed'},101);
 await expect(page.getByRole('button',{name:'查看分析结果',exact:true})).toHaveCount(0);
 await expect(page).toHaveURL(new RegExp(`/analysis/${task}$`));
 await notice(page,'notification_status',{task_id:task,warning:null,sync_pending:false});
 await expect(page).toHaveURL(new RegExp(`/novels/${novel}\\?task_id=${task}$`));
 await expect(page.getByText('暂无诊断数据')).toBeVisible();
 await page.screenshot({path:info.outputPath('completed-results.png'),fullPage:true});
 await page.goBack();
 await expect(page).toHaveURL(new RegExp(`/novels/${novel}$`));
 await expect(page.getByRole('region',{name:'分析工作台'})).toHaveCount(0);
});

test('已完成任务从选择器直接进入结果',async({page})=>{
 await fixture(page,'diagnose',[20,30],{status:'completed'});
 await page.goto(`/novels/${novel}`);
 await page.getByRole('button',{name:'选择任务',exact:true}).click();
 await page.getByText('task-wor',{exact:true}).click();
 await expect(page).toHaveURL(new RegExp(`/novels/${novel}\\?task_id=${task}$`));
 await expect(page.getByText('暂无诊断数据')).toBeVisible();
 await expect(page.getByRole('region',{name:'分析工作台'})).toHaveCount(0);
});

test('直接打开已完成任务等待本次快照，再自动进入结果',async({page})=>{
 const data=await fixture(page,'diagnose',[20,30],{status:'completed',deferSnapshot:true});
 await expect(page).toHaveURL(new RegExp(`/analysis/${task}$`));
 await expect(page.getByText('暂无诊断数据')).toHaveCount(0);
 await expect(page.getByRole('button',{name:'查看分析结果',exact:true})).toHaveCount(0);
 await notice(page,'snapshot',data,data.cursor);
 await expect(page).toHaveURL(new RegExp(`/novels/${novel}\\?task_id=${task}$`));
 await expect(page.getByText('暂无诊断数据')).toBeVisible();
});
