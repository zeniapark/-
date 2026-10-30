import {mkdtempSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {spawn,spawnSync} from 'node:child_process';
import assert from 'node:assert/strict';
import net from 'node:net';

const root=new URL('..',import.meta.url).pathname;
const persist=mkdtempSync(join(tmpdir(),'hanaro-worker-'));
const port=await new Promise((resolve,reject)=>{
  const listener=net.createServer();
  listener.once('error',reject);
  listener.listen(0,'127.0.0.1',()=>{
    const address=listener.address();
    listener.close(()=>resolve(address.port));
  });
});
const baseEnv={...process.env,XDG_CONFIG_HOME:join(persist,'config'),NPM_CONFIG_CACHE:join(persist,'npm-cache')};
const run=(command,args,options={})=>{
  const result=spawnSync(command,args,{cwd:root,encoding:'utf8',env:baseEnv,...options});
  if(result.status!==0)throw new Error(result.stderr||result.stdout);
  return result.stdout;
};
let server;
try{
  run(process.platform==='win32'?'npx.cmd':'npx',['wrangler','d1','migrations','apply','DB','--local','--persist-to',persist]);
  const inviteOutput=run(process.execPath,['scripts/create-admin-invite.mjs','owner@example.com','http://127.0.0.1:'+port,'--local'],{env:{...baseEnv,WRANGLER_PERSIST_TO:persist}});
  const adminInvite=JSON.parse(inviteOutput.trim().split('\n').at(-1));
  server=spawn(process.platform==='win32'?'npx.cmd':'npx',['wrangler','dev','--local','--port',String(port),'--persist-to',persist],{cwd:root,env:baseEnv,stdio:['ignore','pipe','pipe'],detached:process.platform!=='win32'});
  const base=`http://127.0.0.1:${port}`;
  for(let attempt=0;attempt<100;attempt++){
    try{const response=await fetch(base+'/api/me');if(response.ok)break}catch{}
    await new Promise(resolve=>setTimeout(resolve,100));
    if(attempt===99)throw new Error('Worker did not become ready');
  }
  const call=async(path,data,cookie='')=>{
    const response=await fetch(base+'/api/'+path,{method:data===undefined?'GET':'POST',headers:{...(data===undefined?{}:{'Content-Type':'application/json'}),...(cookie?{Cookie:cookie}:{})},body:data===undefined?undefined:JSON.stringify(data)});
    return {status:response.status,body:await response.json(),cookie:response.headers.get('set-cookie')?.split(';')[0]||cookie,headers:response.headers};
  };
  assert.equal((await call('records')).status,401);
  const adminSignup=await call('signup',{email:'owner@example.com',password:'Owner123!',initials:'H',invitation_token:adminInvite.invitation_token});
  assert.equal(adminSignup.status,200,JSON.stringify(adminSignup.body));
  const adminCookie=adminSignup.cookie;
  assert.equal((await call('me',undefined,adminCookie)).body.user.is_admin,1);
  const invite=await call('invitations',{email:'member@example.com'},adminCookie);
  assert.equal(invite.status,201);
  const memberSignup=await call('signup',{email:'member@example.com',password:'Member123!',initials:'K',invitation_token:invite.body.invitation_token});
  assert.equal(memberSignup.status,200);
  const memberCookie=memberSignup.cookie;
  assert.equal((await call('users',undefined,memberCookie)).status,403);
  const record=await call('records',{kind:'문의글',date:'2026-10-30',market:'네이버',category:'제품',order_no:'ORDER-1',model:'MODEL-1',content:'제품 문의',answer:'답변'},memberCookie);
  assert.equal(record.status,201);
  const records=await call('records',undefined,memberCookie);
  assert.equal(records.body.length,1);
  assert.equal(records.body[0].initials,'K');
  const users=await call('users',undefined,adminCookie);
  const member=users.body.find(user=>user.email==='member@example.com');
  assert.equal((await call('users/access',{id:member.id,approved:false},adminCookie)).status,200);
  assert.equal((await call('records',undefined,memberCookie)).status,401);
  assert.equal((await call('invitations',{email:'unused@example.com'},memberCookie)).status,401);
  const page=await fetch(base+'/');
  assert.equal(page.status,200);
  assert.match(await page.text(),/HANARO/);
  assert.equal(page.headers.get('x-frame-options'),'DENY');
  console.log('PASS: Cloudflare Worker signup, roles, invitation, shared records, blocking, static site and security headers');
} finally {
  if(server && server.exitCode===null){
    if(process.platform==='win32')server.kill('SIGTERM');
    else process.kill(-server.pid,'SIGTERM');
    await Promise.race([
      new Promise(resolve=>server.once('exit',resolve)),
      new Promise(resolve=>setTimeout(resolve,2000))
    ]);
  }
  rmSync(persist,{recursive:true,force:true});
}
