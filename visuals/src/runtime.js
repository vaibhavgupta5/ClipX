import {gsap} from 'gsap';
import {createGSAPFrameAdapter} from 'clipz-hyperframes-adapter';
import {compose, formatCount} from './templates/index.js';
gsap.defaults({force3D:false,lazy:false});
const colors={idle:'#273243',active:'#70f1bd',accepted:'#70f1bd',rejected:'#fb8f8f',unknown:'#ffd184'};
window.clipz = {
  async init(doc, assets={}) {
    const root=document.getElementById('scene');
    const theme=doc.spec.tokens.theme;
    root.className=`${theme} ${doc.placement.slot} t-${doc.spec.content.template}`;
    root.style.setProperty('--accent', {mint:'#70f1bd',violet:'#b3a0ff',amber:'#ffd184',red:'#ff4545',
      teal:'#3fe0cf',white:'#f2f2f2',yellow:'#f4e64a'}[doc.spec.tokens.accent]);
    root._strokeWidth=theme==='mono'?3.5:5;
    compose(root,doc.spec,assets);
    const faces=['400 30px ClipZInter','700 30px ClipZInter','400 30px ClipZDisplay','400 30px ClipZMono','700 30px ClipZMono'];
    await Promise.all([...faces.map(f=>document.fonts.load(f)), document.fonts.load('400 30px ClipZHindi','देवनागरी')]);
    await document.fonts.ready;
    if([...faces,'400 30px ClipZHindi'].some(f=>!document.fonts.check(f)))throw Error('Required local font missing');
    await Promise.all([...root.querySelectorAll('img')].map(async img=>{
      await img.decode();if(!img.naturalWidth)throw Error('Missing scene image');
    }));
    root._layout?.();
    const errors=[];
    for(const n of root.querySelectorAll('h1,h2,.card-label,.detail,pre,.comparison,p,blockquote,.counter-value,.counter-label,.bar-label,.tile-label,.tile-caption,.check-label,.impact-headline,.impact-kicker,.hub-label,.spoke-label')) {
      const original=parseFloat(getComputedStyle(n).fontSize);
      // Condensed display faces carry ascent/descent beyond a tight line box by design;
      // allow that ink slack vertically only. Width overflow stays strict.
      const display=/ClipZDisplay/.test(getComputedStyle(n).fontFamily);
      let size=original;
      const over=()=>n.scrollWidth>n.clientWidth+2||n.scrollHeight>n.clientHeight+(display?size*.42:2);
      while(over()&&size>original*.76){size-=1;n.style.fontSize=`${size}px`;}
      if(over()) errors.push(`Text overflow: ${n.textContent.slice(0,50)}`);
    }
    const body=root.querySelector('main'), result=root.querySelector('.result');
    if(body.getBoundingClientRect().bottom>result.getBoundingClientRect().top-12)errors.push('Scene body intersects protected footer/caption region');
    if(errors.length)throw Error(errors.join('; '));
    const tl=gsap.timeline({paused:true});
    const duration=(doc.end_frame-doc.start_frame-0.00001)/30;
    const clock={clock:0}, entrance={p:doc.spec.entrance==='cut'?1:0};
    tl.to(clock,{clock:1,duration,ease:'none'},0);
    if(entrance.p===0)tl.to(entrance,{p:1,duration:Math.min(10,doc.end_frame-doc.start_frame)/30,ease:'power3.out'},0);
    const grouped={}, states={};
    const accent=getComputedStyle(root).getPropertyValue('--accent').trim();
    const mono=theme==='mono';
    const palette={...colors,active:accent,accepted:accent};
    for(const e of doc.events)(grouped[e.target]??=[]).push(e);
    for(const [id,n] of Object.entries(root._targets)) {
      const css=getComputedStyle(n);
      states[id]={opacity:1,y:0,border:css.borderColor,background:css.backgroundColor,
                  focus:0,shadow:0,dash:0,status:n.querySelector?.('.status')?.textContent??'',color:'#a7b4c4',
                  grow:1,count:1,mark:'idle'};
    }
    for(const [id,events] of Object.entries(grouped)) {
      const n=root._targets[id], state=states[id];
      if(events[0].action==='reveal'){state.opacity=0;state.y=24;}
      if(events[0].action==='connect'){state.opacity=0;state.dash=Number(n.dataset.length);}
      // Growth-bearing elements build from zero at their first reveal/update cue.
      const grows=n._fill||n._line, counts=n._counter;
      const first=events.find(e=>e.action==='reveal'||e.action==='update');
      if(grows&&first)state.grow=0;
      if(counts&&first)state.count=0;
      if(first){
        // Clamp to the frames left: the adapter's frame count must equal the placement.
        const at=first.frame/30, left=Math.max(1,doc.end_frame-doc.start_frame-first.frame-1);
        if(grows)tl.to(state,{grow:1,duration:Math.min(Math.max(first.duration_frames,24),left)/30,ease:'power2.out'},at);
        if(counts)tl.to(state,{count:1,duration:Math.min(Math.max(first.duration_frames,36),left)/30,ease:'power2.out'},at);
      }
      for(const e of events) {
        const at=e.frame/30,dur=e.duration_frames/30;
        if(e.action==='reveal')tl.fromTo(state,{opacity:0,y:24},{opacity:1,y:0,duration:dur,ease:'power2.out',immediateRender:false},at);
        if(e.action==='hide')tl.to(state,{opacity:0,duration:dur},at);
        if(e.action==='connect') {
          tl.set(state,{opacity:1,dash:Number(n.dataset.length)},at);
          tl.to(state,{dash:0,duration:dur,ease:'power2.out'},at);
        }
        if(e.action==='highlight'||e.action==='focus')tl.to(state,{border:accent,shadow:id==='body'?0:3,duration:dur},at);
        if(e.action==='focus'&&id==='body'&&root._proof)tl.to(state,{focus:1,duration:dur,ease:'power2.inOut'},at);
        if(e.action==='update') {
          const tint=mono?{rejected:'rgba(255,69,69,0.13)',unknown:'rgba(244,200,74,0.10)'}[e.state]??'rgba(255,255,255,0.06)':e.state==='rejected'?'#38252e':'#17352f';
          tl.to(state,{border:palette[e.state],background:tint,duration:dur},at);
          tl.set(state,{status:e.state.toUpperCase(),color:palette[e.state],mark:e.state},at);
        }
      }
    }
    // Animate plain state objects. DOM styles are written canonically on every seek,
    // avoiding history-dependent compositor layers and CSSPlugin transform caches.
    tl.totalTime(duration,true).totalTime(0,true);
    this.paint=()=>{
      for(const [id,n] of Object.entries(root._targets)) {
        const v=states[id];
        n.style.opacity=String(v.opacity);n.style.transform=`translateY(${v.y.toFixed(4)}px)`;
        if(n instanceof SVGElement){
          n.style.strokeDasharray=n.dataset.length;n.style.strokeDashoffset=String(v.dash);
          if(n._packet){
            const length=Number(n.dataset.length),progress=Math.max(0,Math.min(1,1-v.dash/length));
            const point=n.getPointAtLength(length*progress);
            n._packet.setAttribute('cx',point.x);n._packet.setAttribute('cy',point.y);
            n._packet.style.opacity=String(progress>0&&progress<1?v.opacity:0);
          }
        }
        else {
          if(n._fill)n._fill.style.width=`${(100*n._ratio*v.grow).toFixed(3)}%`;
          if(n._counter){
            n.textContent=formatCount(n._counter,v.count);
            const lit=Math.round(v.count*(n._cells?.length??0));
            n._cells?.forEach((cell,i)=>cell.classList.toggle('on',i<lit));
          }
          if(n._line){
            const length=Number(n._line.dataset.length);
            n._line.style.strokeDasharray=String(length);n._line.style.strokeDashoffset=String(length*(1-v.grow));
            n._line.style.opacity=String(v.opacity);
            const point=n._line.getPointAtLength(length*v.grow);
            n._packet.setAttribute('cx',point.x);n._packet.setAttribute('cy',point.y);
            n._packet.style.opacity=String(v.grow>0&&v.grow<1?v.opacity:0);
          }
          if(n.querySelector('.marks'))n.dataset.state=v.mark;
          n.style.borderColor=v.border;n.style.backgroundColor=v.background;
          n.style.boxShadow=v.shadow?`0 0 0 ${v.shadow.toFixed(4)}px ${accent}`:'none';
          const status=n.querySelector('.status');if(status){status.textContent=v.status;status.style.color=v.color;}
          if(status&&n.classList.contains('check-row'))status.textContent={accepted:'DONE',rejected:'FAILED',unknown:'PENDING'}[v.mark]??'';
        }
      }
      if(root._progress){
        const {text,fill,total}=root._progress;
        const done=[...root.querySelectorAll('.check-row')].filter(r=>r.dataset.state==='accepted').length;
        text.textContent=`${done}/${total} DONE`;fill.style.width=`${(100*done/total).toFixed(3)}%`;
      }
      const stage=root._stage, p=entrance.p, kind=doc.spec.entrance;
      let transform='none', opacity=1;
      // Entrances never start fully transparent/white: frame 0 must pass the blank-scene guard.
      if(kind==='rise'){transform=`translateY(${((1-p)*90).toFixed(3)}px)`;opacity=.35+.65*p;}
      if(kind==='zoom'){transform=`scale(${(1.14-0.14*p).toFixed(5)})`;opacity=.55+.45*p;}
      if(kind==='glitch')transform=`translateX(${(Math.sin(p*41)*36*(1-p)).toFixed(3)}px)`;
      stage.style.transform=transform;stage.style.opacity=String(opacity);
      if(root._veil)root._veil.style.opacity=String(kind==='flash'?.8*(1-p)**1.5:(1-p)*(Math.sin(p*29)>0?.9:.35));
      if(root._impactBg)root._impactBg.style.transform=`scale(${(1.02+0.1*clock.clock).toFixed(5)})`;
      if(root._proof){
        const {img,viewport,c,annotations}=root._proof;
        const base=c.crop,focus=c.focus_crop??base,p=states.body.focus;
        const [x,y,w,h]=base.map((v,i)=>v+(focus[i]-v)*p);
        const W=img.naturalWidth,H=img.naturalHeight;
        const scale=Math.min(viewport.clientWidth/(W*w),viewport.clientHeight/(H*h));
        const left=(viewport.clientWidth-W*w*scale)/2-x*W*scale;
        const top=(viewport.clientHeight-H*h*scale)/2-y*H*scale;
        Object.assign(img.style,{width:`${W*scale}px`,height:`${H*scale}px`,left:`${left}px`,top:`${top}px`});
        for(const [ann,n] of annotations)Object.assign(n.style,{
          left:`${left+ann.x*W*scale}px`,top:`${top+ann.y*H*scale}px`,
          width:`${ann.width*W*scale}px`,height:`${ann.height*H*scale}px`});
      }
    };
    const adapter=createGSAPFrameAdapter({id:doc.spec.id,fps:30,timeline:tl});
    await adapter.init({compositionId:doc.spec.id,fps:30,width:1080,height:1920,root});
    gsap.ticker.sleep();
    this.adapter=adapter;this.doc=doc;this.ready=true;
    return {ready:true,frameCount:adapter.getDurationFrames(),errors};
  },
  async seek(frame) {
    if(!this.ready)throw Error('Scene readiness barrier not reached');
    await this.adapter.seekFrame(frame); this.paint(); gsap.ticker.sleep();
    return {frame,ready:true};
  },
  destroy(){this.adapter?.destroy?.();gsap.globalTimeline.clear();this.ready=false;}
};
