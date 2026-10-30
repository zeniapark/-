import {createHash, randomBytes} from 'node:crypto';
import {spawnSync} from 'node:child_process';

const args=process.argv.slice(2);
const localIndex=args.indexOf('--local');
const local=localIndex!==-1;
if(local)args.splice(localIndex,1);
const email=String(args[0]||'').trim().toLowerCase();
const baseUrl=String(args[1]||'').replace(/\/$/,'');
if(!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)){
  console.error('Usage: node scripts/create-admin-invite.mjs EMAIL [SITE_URL] [--local]');
  process.exit(1);
}
const token=randomBytes(32).toString('base64url');
const hash=createHash('sha256').update(token).digest('hex');
const expires=new Date(Date.now()+7*86400_000).toISOString();
const created=new Date().toISOString();
const escape=value=>value.replaceAll("'","''");
const command=`INSERT INTO invitations(token_hash,email,expires,is_admin,created_at) VALUES('${hash}','${escape(email)}','${expires}',1,'${created}');`;
const wranglerArgs=['wrangler','d1','execute','DB',local?'--local':'--remote','--command',command];
if(process.env.WRANGLER_PERSIST_TO)wranglerArgs.push('--persist-to',process.env.WRANGLER_PERSIST_TO);
const result=spawnSync(process.platform==='win32'?'npx.cmd':'npx',wranglerArgs,{encoding:'utf8',stdio:['ignore','pipe','pipe']});
if(result.status!==0){
  process.stderr.write(result.stderr||result.stdout);
  process.exit(result.status||1);
}
const params=new URLSearchParams({invite:token,email});
console.log(JSON.stringify({email,expires,invitation_token:token,signup_url:baseUrl?`${baseUrl}/#${params}`:null}));
