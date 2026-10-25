/* motor.js — lógica compartida del simulador (extraída de comprador.html). Sin DOM propio salvo toast/$. */
/* ═══════════ MOTOR (igual al del prototipo y a engine/engine.py) ═══════════ */
const Engine=(()=>{
  const parse=s=>{const [y,m,d]=s.split('-').map(Number);return{y,m,d}};
  const isLastFeb=({y,m,d})=>m===2&&d===new Date(Date.UTC(y,2,0)).getUTCDate();
  function days360(a,b){const A=parse(a),B=parse(b);let d1=A.d,d2=B.d;
    if(isLastFeb(A)&&isLastFeb(B))d2=30;if(isLastFeb(A))d1=30;
    if(d2===31&&d1>=30)d2=30;if(d1===31)d1=30;
    return(B.y-A.y)*360+(B.m-A.m)*30+(d2-d1)}
  const daysActual=(a,b)=>(Date.parse(b)-Date.parse(a))/86400000;
  function timeline(pactado,pagos){const map=new Map();
    for(const p of pactado){const r=map.get(p.fecha)||{fecha:p.fecha,D:0,F:0};r.D+=p.valor;map.set(p.fecha,r)}
    for(const p of pagos){const r=map.get(p.fecha)||{fecha:p.fecha,D:0,F:0};r.F+=p.valor;map.set(p.fecha,r)}
    return[...map.values()].sort((a,b)=>a.fecha.localeCompare(b.fecha))}
  function liquidacion(pactado,pagos,tasaCia,tasaCliente){
    const rows=timeline(pactado,pagos);let I=0,J=0,totalH=0;
    rows.forEach((r,k)=>{let H=0;
      if(k===0){I=(0<r.F)?0:-r.F;if(I<0)I=0;J=r.D-r.F}
      else{const prev=rows[k-1],rate=J>=0?tasaCliente:tasaCia;
        H=rate*(12*days360(prev.fecha,r.fecha)/360)*J;
        const IH=I+H;let nI,nJ;
        if(IH<0){nI=(IH+r.D)>=0?0:IH+r.D;nJ=(IH+r.D)>=0?J+(IH+r.D)-r.F:J-r.F}
        else{nI=IH<r.F?0:IH-r.F;nJ=J+r.D-(IH<r.F?r.F-IH:0)}
        I=nI;J=nJ}
      totalH+=H});
    return{ajuste:totalH}}
  function vpn(pactado,pagos,tasa){
    const all=[...pactado,...pagos].map(p=>p.fecha).sort();const t0=all[0],tN=all[all.length-1];
    const m=f=>daysActual(t0,f)/(365/12);
    const pv=fl=>fl.reduce((s,p)=>s+p.valor/Math.pow(1+tasa,m(p.fecha)),0);
    return{ajuste:(pv(pactado)-pv(pagos))*Math.pow(1+tasa,m(tN))}}
  function evaluar({pactado,recaudo,propuesta,cfg,valorVenta}){
    const pagos=[...recaudo,...propuesta];let ajuste;
    if(cfg.metodo==='liquidacion')ajuste=liquidacion(pactado,pagos,cfg.tasaCia,cfg.tasaCliente).ajuste;
    else ajuste=vpn(pactado,pagos,cfg.tasaVpn).ajuste;
    ajuste=Math.round(ajuste);
    const tope=Math.round(valorVenta*cfg.topePct);
    const topado=ajuste<0&&-ajuste>tope;
    const aplicado=topado?-tope:ajuste;
    return{ajuste:aplicado,topado,tope,requiereAprobacion:aplicado<0&&-aplicado>valorVenta*cfg.umbralPct}}
  return{days360,evaluar}
})();
/* ═══════════ UTILIDADES ═══════════ */
const $=s=>document.querySelector(s);
const esc=s=>String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const num=v=>Math.round(Math.abs(v)).toLocaleString('es-CO');
const fmt=v=>(v<0?'−$ ':'$ ')+num(v);
const fmtM=v=>'$ '+(v/1e6).toLocaleString('es-CO',{maximumFractionDigits:1})+' M';
const iso=d=>d.toISOString().slice(0,10);
const dmy=s=>s.split('-').reverse().join('/');
const fLarga=s=>new Date(s+'T12:00:00').toLocaleDateString('es-CO',{day:'numeric',month:'long',year:'numeric'});
const MESES=['ene','feb','mar','abr','may','jun','jul','ago','sep','oct','nov','dic'];
const mesCorto=s=>{const [y,m]=s.split('-');return`${MESES[Number(m)-1]} ${y}`};
const parseNum=s=>{const n=Number(String(s).replace(/\./g,'').replace(/[^\d,-]/g,'').replace(',','.'));return isFinite(n)?n:0};
const now=new Date();
const CORTE=iso(new Date(Date.UTC(now.getFullYear(),now.getMonth(),now.getDate())));
function addM(k,day){const d=new Date(CORTE+'T00:00:00Z');const t=new Date(Date.UTC(d.getUTCFullYear(),d.getUTCMonth()+k,1));const last=new Date(Date.UTC(t.getUTCFullYear(),t.getUTCMonth()+1,0)).getUTCDate();t.setUTCDate(Math.min(day,last));return iso(t)}
const fechaValida=f=>f&&f>'1900-01-01'?f:null;
let uid=1;const nid=()=>'r'+(uid++);
function toast(m){const t=$('#toast');t.textContent=m;t.classList.add('on');clearTimeout(toast.h);toast.h=setTimeout(()=>t.classList.remove('on'),2600)}

/* ═══════════ ANÁLISIS (misma lógica del prototipo) ═══════════ */
function analizar(n){
  const pactado=n.plan_pagos.map(p=>({fecha:p.fecha_pp,valor:p.valor,concepto:p.concepto}));
  const recaudo=n.recaudo.map(r=>({fecha:r.fecha,valor:r.valor,concepto:r.concepto}));
  let disp=recaudo.reduce((s,r)=>s+r.valor,0);const pend=[];
  for(const p of[...pactado].sort((a,b)=>a.fecha.localeCompare(b.fecha))){
    const usado=Math.min(disp,p.valor);disp-=usado;const resto=p.valor-usado;
    if(resto>0.5)pend.push({...p,valor:resto,vencida:p.fecha<CORTE})}
  const totPact=pactado.reduce((s,p)=>s+p.valor,0),totRec=recaudo.reduce((s,r)=>s+r.valor,0);
  const vencido=pend.filter(p=>p.vencida).reduce((s,p)=>s+p.valor,0);
  const fechaLimite=fechaValida(n.fecha_escrituracion_programada)||pactado.map(p=>p.fecha).sort().pop();
  const credito=n.valor_credito||0,fechaCredito=fechaValida(n.fecha_credito)||fechaLimite;
  const base=[...pend.map(p=>({fecha:p.vencida?CORTE:p.fecha,valor:p.valor})),...(credito>0?[{fecha:fechaCredito,valor:credito}]:[])];
  const mora=n.plan_pagos.reduce((s,p)=>{const m=p.int_mora||0,a=p.int_aplicado||0;if(a===1)return s;return s+Math.max(0,m-a)},0);
  return{pend,base,credito,fechaCredito,totRec,saldo:totPact-totRec,vencido,mora:Math.round(mora),fechaLimite,recaudo}
}
function initPropuesta(a){
  const vencidas=a.pend.filter(p=>p.vencida),futuras=a.pend.filter(p=>!p.vencida);
  const totalVencido=vencidas.reduce((s,p)=>s+p.valor,0);
  if(totalVencido===0)return futuras.map(p=>({id:nid(),fecha:p.fecha,concepto:p.concepto,valor:p.valor,orig:p.valor,origFecha:p.fecha,fijo:false}));
  if(futuras.length===0)return[{id:nid(),fecha:CORTE,concepto:vencidas[0].concepto,valor:totalVencido,orig:totalVencido,origFecha:CORTE,fijo:true}];
  return futuras.map((p,i)=>({id:nid(),fecha:p.fecha,concepto:p.concepto,valor:i===0?p.valor+totalVencido:p.valor,orig:p.valor,origFecha:p.fecha,fijo:i===0}));
}
function rebalancear(s,a){
  const libres=s.propuesta.filter(p=>!p.fijo).sort((x,y)=>x.fecha.localeCompare(y.fecha));
  if(!libres.length)return;
  const totFijos=s.propuesta.filter(p=>p.fijo).reduce((t,p)=>t+p.valor,0);
  const saldo=Math.max(0,a.saldo-totFijos),base=Math.floor(saldo/libres.length);
  for(let i=0;i<libres.length-1;i++)libres[i].valor=base;
  libres[libres.length-1].valor=Math.round(saldo-base*(libres.length-1));
}
function calc(s,a,N,CFG){
  const propuesta=s.propuesta.map(p=>({fecha:p.fecha,valor:p.valor}));
  const totProp=propuesta.reduce((t,p)=>t+p.valor,0);
  const dif=Math.round(a.saldo-totProp),excedente=Math.max(0,-dif);
  const nuevoCred=Math.max(0,N.valor_credito-excedente);
  const propMotor=[...propuesta,...(a.credito>0?[{fecha:a.fechaCredito,valor:nuevoCred}]:[])];
  const ev=Engine.evaluar({pactado:a.base,recaudo:[],propuesta:propMotor,cfg:CFG,valorVenta:N.valor_venta});
  const errores=[];
  if(dif>1)errores.push(`Faltan ${fmt(dif)} por asignar a las cuotas.`);
  if(s.propuesta.some(p=>p.fecha<CORTE))errores.push('Hay cuotas con fecha anterior a hoy.');
  if(s.propuesta.some(p=>p.fecha>a.fechaLimite))errores.push(`Todas las cuotas deben quedar antes del ${fLarga(a.fechaLimite)}.`);
  if(s.propuesta.some(p=>!p.abono&&p.valor>0&&p.valor<CFG.cuotaMin))errores.push(`Cada cuota debe ser de al menos ${fmt(CFG.cuotaMin)}, salvo los abonos.`);
  if(s.propuesta.some(p=>!(p.valor>0)))errores.push('Hay cuotas en cero. Elimínalas o asígnales un valor.');
  return{totProp,dif,excedente,nuevoCred,ev,errores}
}

/* ═══════════ LÍNEA DE PAGOS ═══════════ */
function lineaSVG(a,s){
  const buckets=new Map();
  const get=k=>{if(!buckets.has(k))buckets.set(k,{pag:0,act:0,pro:0,venc:false});return buckets.get(k)};
  a.recaudo.forEach(r=>get(r.fecha.slice(0,7)).pag+=r.valor);
  a.pend.forEach(p=>{const b=get(p.fecha.slice(0,7));b.act+=p.valor;if(p.vencida)b.venc=true});
  s.propuesta.forEach(p=>get(p.fecha.slice(0,7)).pro+=p.valor);
  get(CORTE.slice(0,7));
  const keys=[...buckets.keys()].sort();
  // llena meses vacíos para que el eje sea proporcional al tiempo
  const full=[];let [y,m]=keys[0].split('-').map(Number);const [yE,mE]=keys[keys.length-1].split('-').map(Number);
  while(y<yE||(y===yE&&m<=mE)){full.push(`${y}-${String(m).padStart(2,'0')}`);m++;if(m>12){m=1;y++}}
  const cred=a.credito>0;
  const W=360,H=190,base=152,top=16,padX=4,alto=base-top;
  const slots=full.length+(cred?2:0);
  const step=(W-2*padX)/slots,bw=Math.max(3,Math.min(18,step*.68));
  const topes=[...buckets.values()].flatMap(b=>[b.act,b.pro]);
  const max=Math.max(...topes,1);
  const hh=v=>Math.min(alto,v/max*alto);
  const cx=i=>padX+step*i+step/2;
  let g='';
  full.forEach((k,i)=>{const b=buckets.get(k);if(!b)return;const x=cx(i)-bw/2;
    if(b.pag>0){const h=hh(b.pag);g+=`<rect x="${x}" y="${base-h}" width="${bw}" height="${h}" rx="1.5" fill="var(--pagado)"/>`}
    if(b.pro>0){const h=hh(b.pro);g+=`<rect x="${x}" y="${base-h}" width="${bw}" height="${h}" rx="1.5" fill="var(--propuesta)"/>`}
    if(b.act>0){const h=hh(b.act);g+=`<rect x="${x-1.5}" y="${base-h-1.5}" width="${bw+3}" height="${h+1.5}" rx="2" fill="none" stroke="${b.venc?'var(--sobre)':'var(--tinta)'}" stroke-width="2" stroke-dasharray="4 3"/>`}
  });
  // crédito: columna aparte al final, recortada a la altura del gráfico (marca de corte)
  let xCred=0;
  if(cred){const w=bw*1.7;xCred=cx(slots-1);const x=xCred-w/2;
    g+=`<rect x="${x}" y="${top}" width="${w}" height="${alto}" rx="2" fill="var(--credito)"/>
        <path d="M${x-1} ${top+alto*.55}l${w+2} -7M${x-1} ${top+alto*.55+7}l${w+2} -7" stroke="var(--papel)" stroke-width="3"/>`}
  const iHoy=full.indexOf(CORTE.slice(0,7)),dia=Number(CORTE.slice(8,10));
  const xHoy=padX+step*(iHoy+Math.min(dia,30)/30);
  const anclaHoy=xHoy>W-34?'end':xHoy<34?'start':'middle';
  const finCuotas=padX+step*full.length;
  const marcas=[0,full.length-1].filter((v,i,ar)=>ar.indexOf(v)===i);
  const eje=marcas.map((i,j)=>`<text x="${j===0?padX:finCuotas}" y="${base+22}" font-size="13" fill="#52646C" text-anchor="${j===0?'start':'end'}">${mesCorto(full[i])}</text>`).join('')
    +(cred?`<text x="${W-padX}" y="${top-6}" font-size="13" font-weight="600" fill="var(--credito)" text-anchor="end">Crédito</text>`:'');
  const resumen=`Línea de pagos de ${mesCorto(full[0])} a ${mesCorto(full[full.length-1])}. Barras grises: pagado. Contorno punteado: plan actual. Barras azules: tu propuesta.${cred?' La barra final es el crédito hipotecario.':''}`;
  return`<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(resumen)}">
    <line x1="${padX}" x2="${W-padX}" y1="${base}" y2="${base}" stroke="var(--linea)" stroke-width="1.5"/>
    ${g}
    <line x1="${xHoy}" x2="${xHoy}" y1="${top-4}" y2="${base+4}" stroke="var(--tinta)" stroke-width="1.5"/>
    <text x="${xHoy}" y="${top-6}" font-size="13" font-weight="600" fill="var(--tinta)" text-anchor="${anclaHoy}">Hoy</text>
    ${eje}</svg>`
}

