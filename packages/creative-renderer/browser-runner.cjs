// Trusted driver; input contains bounded data only. No credentials enter this process.
const fs=require('node:fs');const path=require('node:path');
const {chromium}=require('../../apps/web/node_modules/@playwright/test');
(async()=>{
 const config=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));
 const request=config.request;
 const browser=await chromium.launch({headless:true,args:['--use-angle=swiftshader','--enable-unsafe-swiftshader','--disable-dev-shm-usage']});
 try {
  const context=await browser.newContext({viewport:request.dimensions,deviceScaleFactor:1,serviceWorkers:'block',offline:true});
  await context.route('**/*',route=>route.abort());
  const page=await context.newPage();
  await page.setContent('<html><head></head><body style="margin:0;overflow:hidden"></body></html>');
  await page.addScriptTag({content:fs.readFileSync(path.join(__dirname,'dist/browser',request.engine+'.js'),'utf8')});
  await page.evaluate(async request=>{window.drawFrame=await AMCAdapter.prepare(request);},request);
  for(let frame=0;frame<request.clock.total_frames;frame++){
   await page.evaluate(async frame=>{await window.drawFrame(frame);},frame);
   await page.screenshot({path:path.join(config.output,`frame_${String(frame).padStart(4,'0')}.png`),type:'png',animations:'disabled'});
  }
 }finally{await browser.close();}
})().catch(error=>{console.error(error.stack);process.exitCode=1;});
