// Reviewed templates only. No string from a transcript is interpreted as markup.
export function el(tag, cls, text, parent) {
  const n=document.createElement(tag); if(cls)n.className=cls;
  if(text!==undefined)n.textContent=text; if(parent)parent.append(n); return n;
}
export function targets(root, id, n) { n.dataset.element=id; root._targets[id]=n; return n; }
const NS='http://www.w3.org/2000/svg';
function svgEl(tag, attrs, parent) {
  const n=document.createElementNS(NS,tag);
  for(const [k,v] of Object.entries(attrs))n.setAttribute(k,String(v));
  if(parent)parent.append(n); return n;
}
function card(root, item, parent) {
  const box=targets(root,item.id,el('div','card',undefined,parent));
  el('div','card-label',item.label,box); if(item.detail)el('div','detail',item.detail,box);
  el('div','status','',box); return box;
}
// Reviewed 24x24 stroke pictograms. Content can only name one; it never supplies geometry.
const P={
  browser:['M3 5h18v14H3z','M3 9h18','M6 7h.01','M8.5 7h.01'],
  mobile:['M7 2h10v20H7z','M11 18h2'],
  server:['M3 4h18v7H3z','M3 13h18v7H3z','M7 7.5h.01','M7 16.5h.01','M11 7.5h6','M11 16.5h6'],
  database:['M4 5c0-1.7 3.6-3 8-3s8 1.3 8 3-3.6 3-8 3-8-1.3-8-3z','M4 5v14c0 1.7 3.6 3 8 3s8-1.3 8-3V5','M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3'],
  card:['M2 5h20v14H2z','M2 10h20','M6 15h4'],
  search:['M11 4a7 7 0 1 1 0 14 7 7 0 0 1 0-14z','M16.5 16.5L21 21'],
  user:['M12 4a4 4 0 1 1 0 8 4 4 0 0 1 0-8z','M4 21c0-4 3.6-6 8-6s8 2 8 6'],
  people:['M9 4a3.5 3.5 0 1 1 0 7 3.5 3.5 0 0 1 0-7z','M2 20c0-3.5 3-5.5 7-5.5s7 2 7 5.5','M16 4.3a3.5 3.5 0 0 1 0 6.4','M18 14.8c2.4.6 4 2.4 4 5.2'],
  clock:['M12 3a9 9 0 1 1 0 18 9 9 0 0 1 0-18z','M12 7v5l3.5 2'],
  key:['M8 11a4 4 0 1 1 0 8 4 4 0 0 1 0-8z','M11 12l9-9','M16 7l3 3','M14 9l2 2'],
  cloud:['M7 19h10a4.5 4.5 0 0 0 .5-9A6.5 6.5 0 0 0 5 11.5 3.8 3.8 0 0 0 7 19z'],
  code:['M8 7l-5 5 5 5','M16 7l5 5-5 5','M14 4l-4 16'],
  flask:['M9 3h6','M10 3v6l-5.5 9.5A2 2 0 0 0 6.2 21h11.6a2 2 0 0 0 1.7-2.5L14 9V3','M7 15h10'],
  chip:['M6 6h12v12H6z','M9 9h6v6H9z','M9 2v4','M15 2v4','M9 18v4','M15 18v4','M2 9h4','M2 15h4','M18 9h4','M18 15h4'],
  message:['M4 4h16v12H9l-5 4z','M8 9h8','M8 12h5'],
  phone:['M5 3h4l2 5-2.5 1.5a11 11 0 0 0 6 6L16 13l5 2v4a2 2 0 0 1-2 2A17 17 0 0 1 3 5a2 2 0 0 1 2-2z'],
  shield:['M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z','M9 12l2 2 4-4'],
  plug:['M9 2v5','M15 2v5','M6 7h12v4a6 6 0 0 1-12 0z','M12 17v5'],
  warning:['M12 3l10 18H2z','M12 10v5','M12 18h.01'],
  gear:['M12 9a3 3 0 1 1 0 6 3 3 0 0 1 0-6z','M12 2v3','M12 19v3','M2 12h3','M19 12h3','M4.9 4.9l2.1 2.1','M17 17l2.1 2.1','M4.9 19.1L7 17','M17 7l2.1-2.1'],
  bolt:['M13 2L4 14h7l-1 8 9-12h-7z'],
  doc:['M6 2h9l5 5v15H6z','M14 2v6h6','M9 13h8','M9 17h6'],
};
export function pictogram(name, parent, cls='picto') {
  const svg=svgEl('svg',{viewBox:'0 0 24 24',class:cls},parent);
  for(const d of P[name]??[])svgEl('path',{d},svg);
  return svg;
}
function visual(assets, assetId, picto, parent, imgCls) {
  if(assetId)return image(assets[assetId],imgCls,parent);
  if(picto)return pictogram(picto,parent);
}
function image(src, cls, parent) { const img=el('img',cls,undefined,parent); img.src=src; return img; }
// Fixed vector marks for checklist states; no font glyph dependency.
function stateMarks(parent) {
  const svg=svgEl('svg',{viewBox:'0 0 40 40',class:'marks'},parent);
  svgEl('path',{d:'M9 21 L17 29 L31 12',class:'mark-accepted'},svg);
  svgEl('path',{d:'M11 11 L29 29 M29 11 L11 29',class:'mark-rejected'},svg);
  svgEl('circle',{cx:20,cy:20,r:4,class:'mark-unknown'},svg);
  return svg;
}
export function formatCount(c, progress) {
  const v=c.start+(c.value-c.start)*progress;
  const text=v.toLocaleString('en-US',{minimumFractionDigits:c.decimals,maximumFractionDigits:c.decimals});
  return `${c.prefix}${text}${c.suffix}`;
}
export function compose(root, spec, assets) {
  root._targets={};
  const c=spec.content;
  const stage=el('div','stage',undefined,root); root._stage=stage;
  if(c.template==='impact_title'&&c.asset_id){
    const bg=el('div','impact-bg',undefined,stage); root._impactBg=image(assets[c.asset_id],'',bg);
    el('div','impact-grade',undefined,stage);
  }
  const top=el('header','',undefined,stage);
  el('span','brand','C / Z',top); el('span','eyebrow',spec.eyebrow,top);
  targets(root,'title',el('h1','',spec.title,stage));
  const body=targets(root,'body',el('main',c.template,undefined,stage));
  if(c.template==='architecture_flow'||c.template==='verification_pipeline') {
    if(c.nodes.length<=4)body.classList.add('spacious');
    const grid=el('div','flow-grid',undefined,body);
    for(const [i,item] of c.nodes.entries()){
      const box=card(root,item,grid); el('span','number',String(i+1).padStart(2,'0'),box);
    }
    const svg=svgEl('svg',{class:'connections'},body);
    // Geometry is measured after font readiness by layout().
    root._layout=()=>{
      const base=body.getBoundingClientRect(), scale=base.width/940;
      svg.setAttribute('viewBox',`0 0 940 ${base.height/scale}`);
      for(const edge of c.edges){
        const a=root._targets[edge.source].getBoundingClientRect();
        const b=root._targets[edge.target].getBoundingClientRect();
        const x1=(a.x+a.width/2-base.x)/scale,y1=(a.bottom-base.y)/scale;
        const x2=(b.x+b.width/2-base.x)/scale,y2=(b.top-base.y)/scale;
        const sameRow=Math.abs(a.y-b.y)<10;
        let d;
        if(sameRow){
          const xa=(a.right-base.x)/scale,xb=(b.left-base.x)/scale,y=(a.y+a.height/2-base.y)/scale;
          d=`M ${xa} ${y} L ${xb} ${y}`;
        } else d=`M ${x1} ${y1} C ${x1} ${(y1+y2)/2}, ${x2} ${(y1+y2)/2}, ${x2} ${y2}`;
        const p=svgEl('path',{d,fill:'none',stroke:'var(--accent)','stroke-width':root._strokeWidth},svg);
        targets(root,edge.id,p);
        p.dataset.length=p.getTotalLength();
        p._packet=svgEl('circle',{r:8,fill:'var(--accent)'},svg);
      }
    };
  } else if(c.template==='proof_focus') {
    el('div','source',c.source_label,body);
    const viewport=el('div','proof-viewport',undefined,body);
    const img=image(assets[c.asset_id],'proof-image',viewport);
    const annotations=[];
    for(const ann of c.annotations??[]){
      const box=targets(root,ann.id,el('div','annotation',undefined,viewport));
      if(ann.label)el('span','annotation-label',ann.label,box);
      annotations.push([ann,box]);
    }
    root._proof={img,viewport,c,annotations};
    el('blockquote','',c.excerpt,body);
  } else if(c.template==='product_walkthrough') {
    el('div','window-bar',`● ● ●     ${c.product}`,body);
    el('div','interface-label','ILLUSTRATIVE INTERFACE',body);
    const rows=el('div','steps',undefined,body);for(const step of c.steps)card(root,step,rows);
  } else if(c.template==='before_after') {
    const before=targets(root,'before',el('section','comparison',undefined,body));
    el('span','kicker','BEFORE',before);el('p','',c.before,before);
    const after=targets(root,'after',el('section','comparison after',undefined,body));
    el('span','kicker','AFTER',after);el('p','',c.after,after);
    el('div','change',c.change,body);
  } else if(c.template==='metric_or_code') {
    el('div','metric',c.value,body);el('div','metric-label',c.label,body);
    if(c.code.length) { const code=el('pre','',undefined,body); for(const line of c.code)el('div','',line,code); }
  } else if(c.template==='counter') {
    const value=targets(root,'value',el('div','counter-value',formatCount(c,1),body));
    value._counter=c;
    el('div','counter-label',c.label,body);
    if(c.cells){
      const grid=targets(root,'grid',el('div','cells',undefined,body));
      value._cells=[...Array(c.cells)].map(()=>el('span','cell','',grid));
    }
  } else if(c.template==='bar_chart') {
    if(c.unit)el('div','chart-unit',c.unit,body);
    const max=Math.max(...c.bars.map(b=>b.value))||1;
    for(const bar of c.bars){
      const row=targets(root,bar.id,el('div','bar-row',undefined,body));
      el('div','bar-label',bar.label,row);
      const track=el('div','bar-track',undefined,row);
      row._fill=el('div','bar-fill',undefined,track); row._ratio=bar.value/max;
      el('div','bar-value',bar.display||String(bar.value),row);
    }
  } else if(c.template==='hub') {
    // Fixed 940x860 board: centre disc, cards on a ring, connectors from disc edge to card edge.
    const W=940, H=860, cx=W/2, cy=H/2, n=c.spokes.length, R=n>6?345:322, half=98, rc=134;
    const svg=svgEl('svg',{class:'connections',viewBox:`0 0 ${W} ${H}`},body);
    svgEl('circle',{cx,cy,r:R,class:'hub-orbit'},svg);
    for(const [i,s] of c.spokes.entries()){
      const a=-Math.PI/2+i*2*Math.PI/n, cos=Math.cos(a), sin=Math.sin(a);
      const x=cx+R*cos, y=cy+R*sin, edge=half/Math.max(Math.abs(cos),Math.abs(sin))+8;
      const spoke=targets(root,s.id,el('div','spoke',undefined,body));
      spoke.style.left=`${x-half}px`;spoke.style.top=`${y-half}px`;
      const art=el('div','spoke-art',undefined,spoke); visual(assets,s.asset_id,s.pictogram,art,'spoke-icon');
      el('div','spoke-label',s.label,spoke); stateMarks(el('div','spoke-badge',undefined,spoke));
      const d=`M ${cx+rc*cos} ${cy+rc*sin} L ${x-edge*cos} ${y-edge*sin}`;
      spoke._line=svgEl('path',{d,fill:'none',stroke:'var(--accent)','stroke-width':root._strokeWidth},svg);
      spoke._packet=svgEl('circle',{r:7,fill:'var(--accent)'},svg);
    }
    const center=targets(root,'hub',el('div','hub-center',undefined,body));
    center.style.left=`${cx-rc+6}px`;center.style.top=`${cy-rc+6}px`;
    visual(assets,c.center_asset_id,c.center_pictogram,center,'hub-icon');
    el('div','hub-label',c.center,center);
    root._layout=()=>{for(const s of c.spokes){const n=root._targets[s.id]._line;n.dataset.length=n.getTotalLength();}};
  } else if(c.template==='multi_view') {
    body.classList.add(`tiles-${c.tiles.length}`);
    for(const t of c.tiles){
      const tile=targets(root,t.id,el('section','tile',undefined,body));
      const view=el('div','tile-view',undefined,tile);
      if(t.asset_id)image(assets[t.asset_id],'tile-image',view);
      else if(t.pictogram)pictogram(t.pictogram,view,'picto tile-picto');
      else el('div','tile-glyph',t.glyph,view);
      if(t.glyph&&(t.asset_id||t.pictogram))el('div','tile-badge',t.glyph,view);
      const meta=el('div','tile-meta',undefined,tile);
      el('div','tile-label',t.label,meta); if(t.caption)el('div','tile-caption',t.caption,meta);
    }
  } else if(c.template==='checklist') {
    // Progress is derived from row states on every paint, so it is seek-deterministic.
    const head=el('div','check-progress',undefined,body);
    root._progress={text:el('div','progress-text','',head),fill:el('div','progress-fill','',el('div','progress-track',undefined,head)),total:c.items.length};
    for(const [i,item] of c.items.entries()){
      const row=targets(root,item.id,el('div','check-row',undefined,body));
      el('div','check-index',String(i+1).padStart(2,'0'),row);
      const box=el('div','check-box',undefined,row); stateMarks(box);
      el('div','check-label',item.label,row); if(item.detail)el('div','check-detail',item.detail,row);
      el('div','status','',row);
    }
  } else if(c.template==='impact_title') {
    if(c.kicker)el('div','impact-kicker',c.kicker,body);
    el('div','impact-headline',c.headline,body);
  } else {
    if(c.asset_id)image(assets[c.asset_id],'bridge-logo',body);
    else el('div','orb','↗',body);el('h2','',c.headline,body);el('p','supporting',c.supporting,body);
  }
  const result=targets(root,'result',el('div','result',undefined,stage));
  el('span','result-dot','',result);el('span','',spec.illustrative?'ILLUSTRATIVE DEMO':'SOURCE-BACKED DETAIL',result);
  const footer=el('footer','',undefined,stage);
  el('span','', 'CLIPZ  /  VISUAL STORIES',footer);el('span','',c.template.replaceAll('_',' ').toUpperCase(),footer);
  if(spec.entrance==='flash'||spec.entrance==='glitch')root._veil=el('div',`veil ${spec.entrance}`,undefined,root);
}
