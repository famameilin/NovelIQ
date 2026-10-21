/** 工位只按容量投影布局，执行身份与位置分别处理 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { CapacityModel, CapacitySeat, ExecutionRecord } from "@/store/analysisProjection";
import { executionActivity, executionRole } from "./workbenchLabels";

interface Place { key: string; model: string; slot: number; x: number; y: number; row: number; }
interface Island { key: string; x: number; y: number; places: Place[]; }
interface Props {
  models: CapacityModel[]; seats: CapacitySeat[]; executions: Record<string, ExecutionRecord>;
  selected: string | null; onSelect: (execution: string | null, seat?: CapacitySeat) => void;
}
const point = (x: number, y: number, z = 0) => [(x - y) * .84, (x + y) * .4 - z];
const color = (name: string) => `var(--office-${name})`;
function Polygon({points, fill}: {points: number[][]; fill: string}) {
  return <polygon points={points.map(p => point(p[0], p[1], p[2]).join(",")).join(" ")} fill={color(fill)} />;
}
function Box({x, y, w, d, z, h, top, side = "desk-side"}: {
  x: number; y: number; w: number; d: number; z: number; h: number; top: string; side?: string;
}) {
  return <g><Polygon fill={side} points={[[x+w,y,z],[x+w,y+d,z],[x+w,y+d,z+h],[x+w,y,z+h]]} />
    <Polygon fill={side} points={[[x,y+d,z],[x+w,y+d,z],[x+w,y+d,z+h],[x,y+d,z+h]]} />
    <Polygon fill={top} points={[[x,y,z+h],[x+w,y,z+h],[x+w,y+d,z+h],[x,y+d,z+h]]} /></g>;
}
function Plant({x,y}: {x:number;y:number}) {
  const [cx,cy]=point(x,y,38);
  return <g><Box x={x-8} y={y-8} w={16} d={16} z={0} h={16} top="desk" />
    <ellipse cx={cx} cy={cy} rx={13} ry={18} fill={color("plant")} />
    <ellipse cx={cx+9} cy={cy+5} rx={10} ry={13} fill={color("plant")} /></g>;
}

export function AgentOffice({models,seats,executions,selected,onSelect}:Props) {
  const svg = useRef<SVGSVGElement>(null);
  const [size,setSize]=useState({width:650,height:390});
  const layout=useMemo(()=>{
    const islands:Island[]=[],places:Place[]=[],regions:{model:string;x:number}[]=[];
    let height=350,width=0;
    models.forEach(model=>{
      const count=Math.max(model.capacity,...seats.filter(s=>s.model_id===model.model_id).map(s=>s.slot+1),0);
      regions.push({model:model.model_id,x:width});
      height=Math.max(height,Math.ceil(Math.ceil(count/6)/3)*270+120);
      for(let i=0;i<Math.ceil(count/6);i++) {
        const island:Island={key:`${model.model_id}:${i}`,x:65+width+(i%3)*350,y:100+Math.floor(i/3)*270,places:[]};
        for(let k=0;k<Math.min(6,count-i*6);k++) {
          const slot=i*6+k,p={key:`${model.model_id}:${slot}`,model:model.model_id,slot,x:island.x+49+(k%3)*96,y:island.y+(k<3?-25:140),row:k<3?0:1};
          places.push(p);island.places.push(p);
        }
        islands.push(island);
      }
      width+=Math.min(3,Math.max(1,Math.ceil(count/6)))*350+120;
    });
    return {islands,places,regions,height,width:Math.max(1,width)};
  },[models,seats]);
  const fit=useCallback(()=>{
    const corners=[[0,0],[layout.width,0],[layout.width,layout.height],[0,layout.height]].map(p=>point(p[0],p[1]));
    const xs=corners.map(p=>p[0]),ys=corners.map(p=>p[1]);
    const left=Math.min(...xs)-25,right=Math.max(...xs)+25,top=Math.min(...ys)-90,bottom=Math.max(...ys)+20;
    return {x:(left+right)/2,y:(top+bottom)/2,scale:Math.min((size.width-35)/(right-left),(size.height-45)/(bottom-top))};
  },[layout.width,layout.height,size]);
  const [camera,setCamera]=useState({x:0,y:0,scale:1});
  const cam=useRef(camera);
  useEffect(()=>{cam.current=camera;},[camera]);
  useEffect(()=>{if(!svg.current)return;const observer=new ResizeObserver(([entry])=>setSize({width:entry.contentRect.width,height:390}));observer.observe(svg.current);return()=>observer.disconnect();},[]);
  useEffect(()=>{setCamera(fit());},[fit]);
  const location=useCallback((clientX:number,clientY:number)=>{
    const node=svg.current;if(!node)return {x:0,y:0};
    return new DOMPoint(clientX,clientY).matrixTransform(node.getScreenCTM()!.inverse());
  },[]);
  useEffect(()=>{
    const node=svg.current;if(!node)return;
    const wheel=(e:WheelEvent)=>{
      e.preventDefault();const p=location(e.clientX,e.clientY),old=cam.current;
      const scale=Math.min(4,Math.max(.06,old.scale*Math.exp(-e.deltaY*.0015)));
      setCamera({scale,x:old.x+(p.x-size.width/2)/old.scale-(p.x-size.width/2)/scale,
        y:old.y+(p.y-size.height/2)/old.scale-(p.y-size.height/2)/scale});
    };
    node.addEventListener("wheel",wheel,{passive:false});return()=>node.removeEventListener("wheel",wheel);
  },[location,size]);
  const drag=useRef<{x:number;y:number;cx:number;cy:number;moved:boolean}|null>(null);
  const occupancy=new Map(seats.map(s=>[`${s.model_id}:${s.slot}`,s]));
  const executionFor=(seat?:CapacitySeat)=>seat&&!seat.foreign?Object.values(executions).find(e=>e.reservation_id===seat.reservation_id):undefined;
  const chair=(p:Place)=>{
    const seat=occupancy.get(p.key),execution=executionFor(seat),[cx,cy]=point(p.x,p.y,29),[hx,hy]=point(p.x,p.y,57);
    const tint=seat?.foreign?"foreign":execution?.activity==="error"?"error":"person";
    const label=`${p.model} 工位 ${p.slot+1} · ${seat?.foreign?'其他任务占用':execution?`${executionRole(execution.sub_stage)} · ${execution.chapter_id?`章节 ${execution.chapter_id} · `:''}${executionActivity(execution.activity)}`:seat?'已预留，等待 Agent 启动':'空闲'}`;
    return <g key={p.key} data-workstation={p.key} role="button" tabIndex={0} aria-label={label}
      onKeyDown={event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();onSelect(execution?.invocation_id??null,seat);}}}>
      <title>{label}</title>
      {execution?.invocation_id===selected&&<ellipse cx={cx} cy={cy+22} rx={33} ry={16} fill={color("selection")} />}
      <Box x={p.x-17} y={p.y-14} w={34} d={28} z={8} h={7} top="chair" side="chair" />
      <Box x={p.x-18} y={p.row?p.y+13:p.y-17} w={36} d={5} z={14} h={23} top="chair" side="chair" />
      {seat&&!execution&&!seat.foreign&&<circle cx={cx} cy={cy} r={8} fill={color('active')} stroke={color('person')} strokeWidth={2} />}
      {(execution||seat?.foreign)&&<><ellipse cx={cx} cy={cy} rx={16} ry={18} fill={color(tint)} />
        <circle cx={hx} cy={hy} r={9.5} fill={color("head")} />
        <path d={`M${hx-9} ${hy+1}q-3-16 10-13q12 0 9 12q-8-5-19 1`} fill={color("screen")} /></>}
      {execution&&camera.scale>=1.1&&<text x={cx} y={cy+42} textAnchor="middle" fill="hsl(var(--text))" fontSize={11/camera.scale} pointerEvents="none">
        <tspan x={cx}>{executionRole(execution.sub_stage)}{execution.chapter_id?` · ${execution.chapter_id}章`:''}</tspan>
        <tspan x={cx} dy={14/camera.scale}>{executionActivity(execution.activity)}</tspan>
      </text>}
    </g>;
  };
  if(!models.length)return <div className="py-8 text-sm text-text-muted">模型容量未记录</div>;
  return <div className="agent-office" style={{
    "--office-floor":"hsl(var(--background))","--office-wall":"hsl(var(--border))",
    "--office-desk":"color-mix(in srgb,hsl(var(--primary)) 14%,hsl(var(--surface)))",
    "--office-desk-side":"color-mix(in srgb,hsl(var(--primary)) 24%,hsl(var(--surface)))",
    "--office-chair":"color-mix(in srgb,hsl(var(--text-muted)) 45%,hsl(var(--surface)))",
    "--office-person":"hsl(var(--primary))","--office-foreign":"hsl(var(--text-muted))",
    "--office-screen":"hsl(var(--text-secondary))","--office-active":"hsl(var(--primary-subtle))",
    "--office-head":"color-mix(in srgb,hsl(var(--primary)) 30%,hsl(var(--surface)))",
    "--office-plant":"hsl(var(--chart-positive))","--office-error":"hsl(var(--chart-negative))",
    "--office-selection":"color-mix(in srgb,hsl(var(--primary)) 25%,transparent)",
  } as React.CSSProperties}>
    <svg ref={svg} viewBox={`0 0 ${size.width} ${size.height}`} role="img" aria-label={`${layout.places.length} 个模型容量工位`} className="block h-[390px] w-full select-none touch-none"
      onPointerDown={e=>{const p=location(e.clientX,e.clientY);drag.current={x:p.x,y:p.y,cx:camera.x,cy:camera.y,moved:false};e.currentTarget.setPointerCapture(e.pointerId);}}
      onPointerMove={e=>{const d=drag.current;if(!d)return;const p=location(e.clientX,e.clientY),dx=p.x-d.x,dy=p.y-d.y;if(Math.hypot(dx,dy)>4)d.moved=true;setCamera({...cam.current,x:d.cx-dx/cam.current.scale,y:d.cy-dy/cam.current.scale});}}
      onPointerUp={e=>{const d=drag.current;drag.current=null;if(!d||d.moved)return;const q=location(e.clientX,e.clientY);
        const nearest=layout.places.map(p=>{const a=point(p.x,p.y,35);return {p,d:Math.hypot(size.width/2+(a[0]-camera.x)*camera.scale-q.x,size.height/2+(a[1]-camera.y)*camera.scale-q.y)};}).sort((a,b)=>a.d-b.d)[0];
        if(nearest?.d<28){const seat=occupancy.get(nearest.p.key),execution=executionFor(seat);onSelect(execution?.invocation_id??null,seat);}}}
      onPointerCancel={()=>{drag.current=null;}}>
      <g transform={`translate(${size.width/2} ${size.height/2}) scale(${camera.scale}) translate(${-camera.x} ${-camera.y})`}>
        <Box x={0} y={0} w={layout.width} d={layout.height} z={-9} h={10} top="floor" side="wall" />
        <Box x={0} y={0} w={layout.width} d={9} z={0} h={70} top="wall" side="wall" />
        <Box x={0} y={0} w={9} d={layout.height} z={0} h={70} top="wall" side="wall" />
        {Array.from({length:Math.ceil(layout.width/240)},(_,i)=>{const x=80+i*240;return <Polygon key={x} fill="active" points={[[x,10,28],[x+120,10,28],[x+120,10,58],[x,10,58]]} />;})}
        <Plant x={35} y={35} /><Plant x={layout.width-40} y={layout.height-40} />
        {[...layout.islands].sort((a,b)=>a.x+a.y-b.x-b.y).map(island=><g key={island.key}>
          {island.places.filter(p=>!p.row).map(chair)}
          {[10,276].flatMap(dx=>[10,98].map(dy=><Box key={`${dx}:${dy}`} x={island.x+dx} y={island.y+dy} w={7} d={7} z={0} h={33} top="desk-side" />))}
          <Box x={island.x} y={island.y} w={293} d={115} z={31} h={5} top="desk" />
          <Box x={island.x+5} y={island.y+54} w={283} d={6} z={36} h={11} top="wall" />
          {island.places.map(p=>{const seat=occupancy.get(p.key),y=p.y+(p.row?-40:40);return <g key={p.key}>
            <Box x={p.x-5} y={y-5} w={10} d={10} z={35} h={3} top="screen" />
            <Box x={p.x-2} y={y-2} w={4} d={4} z={38} h={14} top="screen" />
            <Box x={p.x-23} y={y-3} w={46} d={4} z={46} h={29} top={seat&&!seat.foreign?"active":"screen"} />
          </g>;})}
          <Plant x={island.x+146} y={island.y+57} />
          {island.places.filter(p=>p.row).map(chair)}
        </g>)}
      </g>
      {models.map((model,i)=>{const p=point(layout.regions[i].x+70,40,65);return <text key={model.model_id} x={size.width/2+(p[0]-camera.x)*camera.scale} y={size.height/2+(p[1]-camera.y)*camera.scale} fill="hsl(var(--text))" fontSize={12} pointerEvents="none"><title>{model.model_id}</title>{model.model_id.length>24?`${model.model_id.slice(0,21)}…`:model.model_id} · {seats.filter(s=>s.model_id===model.model_id).length}/{model.capacity}</text>;})}
    </svg>
    <div className="flex items-center justify-between px-3 pb-3 text-xs text-text-muted"><span>滚轮缩放 · 拖动平移 · 点击工位查看</span><button type="button" className="text-primary" onClick={()=>setCamera(fit())}>复位视角</button></div>
  </div>;
}
