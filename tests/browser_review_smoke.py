#!/usr/bin/env python3
"""Real-browser review smoke test against an ISOLATED, already built project.

Requires Playwright + its Chromium. Start review-core serve-review --no-open
for the test project first. No renderer is invoked. --write requires a marker
.review-test-project in that project; never run write tests against production.
The sandbox parent implements review-core's wire contract and writes through the
real local host. It is not a substitute for a DSH-window acceptance test.
"""
import argparse
import json
from pathlib import Path
import sys
from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'helpers'))
from lib.planners_modules import resolve_module


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('project',type=Path)
    ap.add_argument('--url',required=True)
    ap.add_argument('--mode',choices=['local','sandbox'],default='sandbox')
    ap.add_argument('--at',type=float,default=0)
    ap.add_argument('--recording-at',type=float)
    ap.add_argument('--write',action='store_true')
    ap.add_argument('--output',type=Path,required=True)
    args=ap.parse_args();root=args.project.resolve();host=args.url.rstrip('/')
    if args.write and not (root/'.review-test-project').exists():
        ap.error('--write requires an isolated .review-test-project marker')
    args.output.mkdir(parents=True,exist_ok=True)
    review=root/'review';data=json.loads((review/'review_data.json').read_text())
    source=(review/'index.html').read_text()
    bridge=(resolve_module('planners-review-core')/'assets/review-bridge.js').read_text()
    source=source.replace('{{REVIEW_BRIDGE}}','<script>'+bridge+'</script>')
    surface=json.loads((review/'review-surface.json').read_text())
    parent='''<style>body{margin:0}iframe{width:100vw;height:100vh;border:0}</style>
    <iframe id="review" sandbox="allow-scripts" allow="autoplay"></iframe><script>
    const frame=document.getElementById('review');
    window.addEventListener('message',async e=>{
      const d=e.data;if(e.source!==frame.contentWindow||!d?.__review)return;
      const reply=x=>frame.contentWindow.postMessage({...x,__review:true,nonce:d.nonce},'*');
      if(d.type==='hello'){reply({type:'init',surface:SURFACE,capabilities:['draft'],host:'contract-test'});return;}
      if(d.type!=='call')return;
      try{
        let value;
        if(d.method==='read'||d.method==='asset'){
          const r=await fetch('/'+d.payload.rel);
          if(!r.ok&&!d.payload.optional)throw Error('Read '+r.status);
          value={bytes:r.ok?await r.arrayBuffer():new ArrayBuffer(0),type:r.headers.get('content-type')};
        }else if(['write','draft','wake'].includes(d.method)){
          const r=await fetch('/__review/'+d.method,{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(d.payload)});
          value=await r.json();if(!r.ok)throw Error(value.error);
        }else throw Error('Unsupported '+d.method);
        reply({type:'result',id:d.id,ok:true,value});
      }catch(err){reply({type:'result',id:d.id,ok:false,error:err.message});}
    });frame.srcdoc=HTML;
    </script>'''.replace('SURFACE',json.dumps(surface)).replace('HTML',json.dumps(source).replace('</script','<\\/script'))
    evidence={'mode':args.mode,'checks':[],'errors':[],'networkFailures':[]}
    def passed(name):evidence['checks'].append(name)
    with sync_playwright() as p:
        # Null audio output avoids the locked macOS hardware clock freezing in
        # headless mode. Media decoding and playback clocks remain enabled.
        browser=p.chromium.launch(headless=True,args=['--autoplay-policy=no-user-gesture-required','--disable-audio-output'])
        page=browser.new_page(viewport={'width':1600,'height':1000})
        page.on('pageerror',lambda e:evidence['errors'].append(str(e)))
        page.on('requestfailed',lambda r:evidence['networkFailures'].append({'url':r.url[:160],'failure':r.failure}))
        # Playback must not need the compile server after build.
        server=data['media']['liveStage']['serverUrl']
        page.route(server+'/**',lambda route:route.abort())
        if args.mode=='sandbox':
            page.route('**/__sandbox',lambda route:route.fulfill(body=parent,content_type='text/html'))
            page.goto(host+'/__sandbox');f=page.frames[1]
        else:page.goto(host+'/review/index.html');f=page.main_frame
        try:
            f.wait_for_function('document.querySelector("#live-stage-frame").ready',timeout=20000)
            f.wait_for_function('document.querySelectorAll(".step[role=button]").length>0')
            passed('official player ready with compile-server network blocked')
            player=f.locator('#live-stage-frame')
            player.evaluate('(p,t)=>p.seek(t)',args.at)
            f.wait_for_timeout(150)
            f.locator('#btn-speed-toggle').click();f.locator('#btn-speed-toggle').click()
            assert player.evaluate('p=>p.playbackRate')==2
            f.locator('#btn-global-play').click()
            f.wait_for_function('(t)=>document.querySelector("#live-stage-frame").currentTime>t',arg=args.at+2,timeout=8000)
            f.locator('#btn-global-play').click()
            assert player.evaluate('p=>p.paused')
            passed('2x playback advances and pause stops the official clock')
            cf=next(x for x in page.frames if x.evaluate('!!document.querySelector("[data-composition-id]")'))
            audio=cf.evaluate('()=>{let a=document.querySelector("audio");return a?{t:a.currentTime,rate:a.playbackRate,ready:a.readyState}:null}')
            if audio:
                assert audio['ready']>=2 and abs(audio['t']-player.evaluate('p=>p.currentTime'))<0.5,audio
                passed('decoded narration and player clocks agree')
            # Use a real caption interval, not a silent gap.
            caption=next(c for c in data['captions'] if c['start']>=args.at)
            player.evaluate('(p,t)=>p.seek(t)',caption['start']+0.1)
            f.wait_for_timeout(200)
            f.locator('#btn-toggle-subtitles').click();assert not f.locator('#canvas-caption-layer').is_visible()
            f.locator('#btn-toggle-subtitles').click();assert f.locator('#canvas-caption-layer').is_visible()
            passed('subtitle toggle follows the live clock')
            # Screen navigation and end-state buttons work on the live stage.
            prior=player.evaluate('p=>p.currentTime')
            f.locator('#btn-next-screen').click();f.wait_for_timeout(200)
            assert player.evaluate('p=>p.currentTime')>prior
            f.locator('#btn-prev-screen').click();f.wait_for_timeout(200)
            assert f.evaluate('document.body.dataset.stage')=='live'
            passed('previous and next screen retain official player ownership')
            if args.recording_at is not None:
                player.evaluate('(p,t)=>p.seek(t)',args.recording_at);f.wait_for_timeout(500)
                video=cf.evaluate('()=>[...document.querySelectorAll("video.clip")].filter(v=>getComputedStyle(v).visibility!=="hidden").map(v=>({t:v.currentTime,start:+v.dataset.start,offset:+(v.dataset.mediaStart||0),ready:v.readyState}))')
                assert video and all(v['ready']>=2 for v in video),video
                assert abs(video[0]['t']-(args.recording_at-video[0]['start']+video[0]['offset']))<0.5,video
                passed('recording seeks to its source offset and decodes a frame')
            player.evaluate('(p,t)=>p.seek(t)',caption['start']+0.2);f.wait_for_timeout(200)
            recompose = bool(data.get('density', {}).get('enabled'))
            if not recompose:
                f.locator('#mode-step').click()
                f.locator('#tool-box').click()
                box=f.locator('#annotation-overlay').bounding_box()
                page.mouse.move(box['x']+box['width']*.55,box['y']+box['height']*.3)
                page.mouse.down();page.mouse.move(box['x']+box['width']*.75,box['y']+box['height']*.5);page.mouse.up()
                passed('box annotation can be drawn over live composition')
            if args.write:
                text_selector, save_selector = ('#vfb-text', '#vfb-save') if recompose else ('#fb-text', '#fb-save')
                f.locator(text_selector).fill('浏览器验收：保留文字，调整此处动画。')
                f.locator(save_selector).click()
                f.wait_for_function('(selector)=>document.querySelector(selector).value===""',arg=text_selector,timeout=5000)
                record=json.loads((review/'review-submissions.json').read_text())['records'][-1]
                assert record.get('unitId') and record['playbackTimeMs']>0,record
                if not recompose:
                    assert record['animationAnchor']['cueIndex'] is not None,record
                    assert record['adjustments']['annotations'],record
                evidence['record']={k:record.get(k) for k in ['unitId','stepId','playbackTimeMs','animationAnchor','snapshot']}
                passed('real host persists current unit, time and snapshot feedback')
            if not recompose: f.locator('#tool-director').click()
            page.screenshot(path=str(args.output/(args.mode+'-light.png')))
            if not recompose:
                f.locator('#theme-mode').select_option('dark')
                page.screenshot(path=str(args.output/(args.mode+'-dark.png')))
                f.locator('#theme-mode').select_option('light')
                page.set_viewport_size({'width':650,'height':1000})
                page.screenshot(path=str(args.output/(args.mode+'-narrow.png')))
                assert f.evaluate('document.documentElement.scrollWidth <= innerWidth+1')
                passed('narrow layout has no horizontal overflow')
            assert not evidence['errors'],evidence['errors']
            assert not evidence['networkFailures'],evidence['networkFailures']
            evidence['ok']=True
        except Exception as error:
            evidence['ok']=False;evidence['failure']=str(error)
            page.screenshot(path=str(args.output/(args.mode+'-failure.png')))
            raise
        finally:
            (args.output/(args.mode+'-result.json')).write_text(json.dumps(evidence,ensure_ascii=False,indent=2))
            print(json.dumps(evidence,ensure_ascii=False,indent=2));browser.close()

if __name__=='__main__':main()
