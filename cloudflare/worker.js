const MARKETS = ['네이버','11번가','G마켓','옥션','오늘의집','쿠팡','카카오','롯데온','SSG','알리','컬리','자사몰','토스'];
const CATEGORIES = ['배송요청사항','제품','구매','반품','상품권','컴플레인','기타'];
const RETURNS = ['배송일정','설치불가','제품불량','단순변심','서비스불만','기타'];
const KINDS = ['문의글','유선','반품','VOC','CS매뉴얼'];
const RETURN_CODES = ['일반반품','착하반품','영업반품'];
const encoder = new TextEncoder();

const securityHeaders = {
  'X-Robots-Tag': 'noindex, nofollow, noarchive',
  'Referrer-Policy': 'no-referrer',
  'X-Content-Type-Options': 'nosniff',
  'X-Frame-Options': 'DENY',
  'Permissions-Policy': 'camera=(), microphone=(), geolocation=()',
  'Content-Security-Policy': "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
};

function secure(response) {
  const result = new Response(response.body, response);
  for (const [name, value] of Object.entries(securityHeaders)) result.headers.set(name, value);
  return result;
}

function json(data, status = 200, headers = {}) {
  return secure(new Response(JSON.stringify(data), {
    status,
    headers: {'Content-Type':'application/json; charset=utf-8','Cache-Control':'no-store',...headers}
  }));
}

function error(message, status = 400) { return json({error: message}, status); }
function now() { return new Date().toISOString(); }
function todayKorea() {
  return new Intl.DateTimeFormat('en-CA', {timeZone:'Asia/Seoul',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
}
function bytesToHex(bytes) { return [...new Uint8Array(bytes)].map(value => value.toString(16).padStart(2,'0')).join(''); }
function randomToken(size = 32) {
  const bytes = crypto.getRandomValues(new Uint8Array(size));
  return btoa(String.fromCharCode(...bytes)).replace(/\+/g,'-').replace(/\//g,'_').replace(/=+$/,'');
}
async function sha256(value) { return bytesToHex(await crypto.subtle.digest('SHA-256', encoder.encode(value))); }
async function passwordHash(password, salt) {
  const key = await crypto.subtle.importKey('raw', encoder.encode(password), 'PBKDF2', false, ['deriveBits']);
  const bits = await crypto.subtle.deriveBits({name:'PBKDF2',hash:'SHA-256',salt:encoder.encode(salt),iterations:100000}, key, 256);
  return bytesToHex(bits);
}
function constantTimeEqual(left, right) {
  if (typeof left !== 'string' || typeof right !== 'string' || left.length !== right.length) return false;
  let result = 0;
  for (let index = 0; index < left.length; index++) result |= left.charCodeAt(index) ^ right.charCodeAt(index);
  return result === 0;
}
function normalizeEmail(value) {
  const email = String(value || '').trim().toLowerCase();
  if (email.length > 254 || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) throw new Error('올바른 이메일 주소를 입력하세요.');
  return email;
}
function text(value, max = 200) {
  const result = String(value ?? '').trim();
  if (result.length > max) throw new Error(`입력값은 ${max}자 이내여야 합니다.`);
  return result;
}
function validDate(value) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value || '')) return false;
  const parsed = new Date(`${value}T00:00:00Z`);
  return !Number.isNaN(parsed.getTime()) && parsed.toISOString().slice(0,10) === value;
}
function cookie(request, name) {
  const raw = request.headers.get('Cookie') || '';
  for (const part of raw.split(';')) {
    const [key, ...rest] = part.trim().split('=');
    if (key === name) return decodeURIComponent(rest.join('='));
  }
  return '';
}
async function body(request) {
  const length = Number(request.headers.get('Content-Length') || 0);
  if (length > 1_000_000) throw new Error('요청이 너무 큽니다.');
  const data = await request.json();
  if (!data || Array.isArray(data) || typeof data !== 'object') throw new Error('올바른 요청 형식을 사용하세요.');
  return data;
}
async function currentUser(env, request) {
  const token = cookie(request, 'session');
  if (!token) return null;
  return env.DB.prepare(`SELECT u.id,u.email,u.initials,u.is_admin
    FROM users u JOIN sessions s ON s.user_id=u.id
    WHERE s.token_hash=? AND s.expires>? AND u.approved=1`).bind(await sha256(token), now()).first();
}
async function requireUser(env, request, admin = false) {
  const user = await currentUser(env, request);
  if (!user) return {response:error('로그인이 필요합니다.',401)};
  if (admin && !user.is_admin) return {response:error('관리자만 이용할 수 있습니다.',403)};
  return {user};
}
async function limited(env, source) {
  const cutoff = Math.floor(Date.now()/1000) - 900;
  await env.DB.prepare('DELETE FROM auth_failures WHERE created_at<?').bind(cutoff).run();
  const row = await env.DB.prepare('SELECT COUNT(*) count FROM auth_failures WHERE source=? AND created_at>=?').bind(source,cutoff).first();
  return Number(row?.count || 0) >= 10;
}
async function failure(env, source) {
  await env.DB.prepare('INSERT INTO auth_failures(source,created_at) VALUES(?,?)').bind(source,Math.floor(Date.now()/1000)).run();
}
async function success(env, source) { await env.DB.prepare('DELETE FROM auth_failures WHERE source=?').bind(source).run(); }
async function startSession(env, userId) {
  const token = randomToken();
  const expires = new Date(Date.now()+7*86400_000).toISOString();
  await env.DB.prepare('INSERT INTO sessions(token_hash,user_id,expires) VALUES(?,?,?)').bind(await sha256(token),userId,expires).run();
  return `session=${encodeURIComponent(token)}; HttpOnly; Secure; SameSite=Lax; Path=/; Max-Age=604800`;
}

async function getApi(request, env, path) {
  if (path === '/api/me') {
    const user = await currentUser(env,request);
    return json({user:user || null,today:todayKorea(),markets:MARKETS,categories:CATEGORIES,returns:RETURNS});
  }
  if (path === '/api/records') {
    const access = await requireUser(env,request); if (access.response) return access.response;
    const rows = await env.DB.prepare(`SELECT r.*,u.initials,u.email FROM records r JOIN users u ON u.id=r.user_id ORDER BY r.date DESC,r.id DESC`).all();
    return json(rows.results || []);
  }
  if (path === '/api/users') {
    const access = await requireUser(env,request,true); if (access.response) return access.response;
    const rows = await env.DB.prepare('SELECT id,email,initials,is_admin,approved FROM users ORDER BY id').all();
    return json(rows.results || []);
  }
  if (path === '/api/invitations') {
    const access = await requireUser(env,request,true); if (access.response) return access.response;
    const rows = await env.DB.prepare('SELECT id,email,expires,is_admin,used_at,revoked_at FROM invitations ORDER BY id DESC').all();
    return json(rows.results || []);
  }
  return error('지원하지 않는 요청입니다.',404);
}

async function signupOrLogin(request, env, path, data) {
  const source = request.headers.get('CF-Connecting-IP') || 'local';
  if (await limited(env,source)) return error('로그인 시도가 너무 많습니다. 15분 뒤 다시 시도하세요.',429);
  const email = normalizeEmail(data.email);
  const password = String(data.password || '');
  if (path === '/api/signup') {
    const initials = text(data.initials,12);
    if (!/^(?=.*[A-Za-z])(?=.*\d)(?=.*[^A-Za-z\d\s])\S{8,15}$/.test(password)) throw new Error('비밀번호는 영문·숫자·특수문자를 포함한 8~15자입니다.');
    if (!initials) throw new Error('담당자 이니셜을 입력하세요.');
    const invitationToken = String(data.invitation_token || '');
    if (invitationToken.length < 20 || invitationToken.length > 200) { await failure(env,source); return error('유효한 초대 링크로 가입해 주세요.',403); }
    const tokenHash = await sha256(invitationToken);
    const salt = randomToken(18);
    const hashed = await passwordHash(password,salt);
    try {
      const results = await env.DB.batch([
        env.DB.prepare(`INSERT INTO users(email,initials,salt,password,is_admin,approved,created_at)
          SELECT ?,?,?,?,is_admin,1,? FROM invitations
          WHERE token_hash=? AND email=? AND expires>? AND used_at IS NULL AND revoked_at IS NULL`)
          .bind(email,initials,salt,hashed,now(),tokenHash,email,now()),
        env.DB.prepare(`UPDATE invitations SET used_at=? WHERE token_hash=? AND email=? AND expires>? AND used_at IS NULL AND revoked_at IS NULL`)
          .bind(now(),tokenHash,email,now())
      ]);
      if (!results[0].meta.changes) { await failure(env,source); return error('초대가 유효하지 않거나 만료되었습니다. 초대받은 이메일을 확인하세요.',403); }
    } catch (cause) {
      if (String(cause).includes('UNIQUE')) throw new Error('이미 가입된 이메일입니다.');
      throw cause;
    }
  }
  const user = await env.DB.prepare('SELECT * FROM users WHERE email=?').bind(email).first();
  const candidate = user ? await passwordHash(password,user.salt) : '';
  if (!user || !constantTimeEqual(user.password,candidate)) { await failure(env,source); return error('이메일 또는 비밀번호를 확인하세요.',401); }
  if (!user.approved) { await failure(env,source); return error('관리자 승인이 필요한 계정입니다. 운영자에게 문의하세요.',403); }
  await success(env,source);
  return json({ok:true},200,{'Set-Cookie':await startSession(env,user.id)});
}

async function postApi(request, env, path) {
  if (request.headers.get('Sec-Fetch-Site') === 'cross-site') return error('허용되지 않은 요청입니다.',403);
  const data = await body(request);
  if (path === '/api/signup' || path === '/api/login') return signupOrLogin(request,env,path,data);
  const access = await requireUser(env,request); if (access.response) return access.response;
  const user = access.user;
  if (path === '/api/logout') {
    const token = cookie(request,'session');
    if (token) await env.DB.prepare('DELETE FROM sessions WHERE token_hash=?').bind(await sha256(token)).run();
    return json({ok:true},200,{'Set-Cookie':'session=; HttpOnly; Secure; SameSite=Lax; Path=/; Max-Age=0'});
  }
  if (path === '/api/invitations') {
    if (!user.is_admin) return error('관리자만 초대를 관리할 수 있습니다.',403);
    const email = normalizeEmail(data.email);
    if (await env.DB.prepare('SELECT 1 found FROM users WHERE email=?').bind(email).first()) throw new Error('이미 가입된 이메일입니다.');
    const token = randomToken();
    const expires = new Date(Date.now()+7*86400_000).toISOString();
    await env.DB.batch([
      env.DB.prepare('INSERT INTO invitations(token_hash,email,expires,is_admin,created_by,created_at) VALUES(?,?,?,?,?,?)').bind(await sha256(token),email,expires,0,user.id,now()),
      env.DB.prepare('INSERT INTO audit(user_id,action,created) VALUES(?,?,?)').bind(user.id,'회원 초대',now())
    ]);
    return json({invitation_token:token,email,expires},201);
  }
  if (path === '/api/invitations/revoke') {
    if (!user.is_admin) return error('관리자만 초대를 관리할 수 있습니다.',403);
    if (!Number.isInteger(data.id)) throw new Error('초대 번호를 확인하세요.');
    const result = await env.DB.prepare('UPDATE invitations SET revoked_at=? WHERE id=? AND used_at IS NULL AND revoked_at IS NULL').bind(now(),data.id).run();
    return result.meta.changes ? json({ok:true}) : error('취소할 수 있는 초대가 없습니다.',404);
  }
  if (path === '/api/users/access') {
    if (!user.is_admin) return error('관리자만 회원을 관리할 수 있습니다.',403);
    if (!Number.isInteger(data.id) || typeof data.approved !== 'boolean') throw new Error('회원 번호와 승인 여부를 확인하세요.');
    if (data.id === user.id && !data.approved) return error('자신의 접근 권한을 차단할 수 없습니다.',400);
    const target = await env.DB.prepare('SELECT id,is_admin,approved FROM users WHERE id=?').bind(data.id).first();
    if (!target) return error('회원을 찾을 수 없습니다.',404);
    if (!data.approved && target.is_admin && target.approved) {
      const count = await env.DB.prepare('SELECT COUNT(*) count FROM users WHERE is_admin=1 AND approved=1').first();
      if (Number(count.count) <= 1) return error('마지막 관리자를 차단할 수 없습니다.',400);
    }
    const statements = [
      env.DB.prepare('UPDATE users SET approved=? WHERE id=?').bind(data.approved?1:0,data.id),
      env.DB.prepare('INSERT INTO audit(user_id,action,created) VALUES(?,?,?)').bind(user.id,`회원 ${data.id} ${data.approved?'승인':'차단'}`,now())
    ];
    if (!data.approved) statements.push(env.DB.prepare('DELETE FROM sessions WHERE user_id=?').bind(data.id));
    await env.DB.batch(statements);
    return json({ok:true});
  }
  if (path === '/api/records') {
    const kind = text(data.kind,20), category = text(data.category,50), date = text(data.date,10);
    if (!KINDS.includes(kind)) throw new Error('등록 구분을 확인하세요.');
    if (!(kind==='반품'?RETURNS:CATEGORIES).includes(category)) throw new Error('카테고리를 확인하세요.');
    if (!validDate(date)) throw new Error('등록일을 확인하세요.');
    const market=text(data.market,50), orderNo=text(data.order_no), model=text(data.model), phone=text(data.phone), customer=text(data.customer);
    const content=text(data.content,20000), answer=text(data.answer,20000), code=text(data.code,30), logistics=text(data.logistics), completed=text(data.completed,10);
    if (!MARKETS.includes(market)) throw new Error('마켓을 선택하세요.');
    if (!content) throw new Error('내용을 입력하세요.');
    if (kind==='유선'&&!phone) throw new Error('전화번호를 입력하세요.');
    if (kind==='반품'&&(!orderNo||!customer||!validDate(completed))) throw new Error('주문번호, 고객명, 반품완료일을 입력하세요.');
    if (kind==='반품'&&!RETURN_CODES.includes(code)) throw new Error('반품 코드를 선택하세요.');
    await env.DB.batch([
      env.DB.prepare(`INSERT INTO records(kind,date,market,category,order_no,model,phone,customer,content,answer,code,logistics,completed,after_ship,user_id,created_at)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)`).bind(kind,date,market,category,orderNo,model,phone,customer,content,answer,code,logistics,completed,kind==='반품'&&data.after_ship?1:0,user.id,now()),
      env.DB.prepare('INSERT INTO audit(user_id,action,created) VALUES(?,?,?)').bind(user.id,'등록',now())
    ]);
    return json({ok:true},201);
  }
  if (path === '/api/export') {
    if (!Array.isArray(data.ids) || data.ids.length > 5000 || data.ids.some(id=>!Number.isInteger(id))) throw new Error('다운로드 범위를 확인하세요.');
    const rows=[];
    for(let offset=0;offset<data.ids.length;offset+=90){
      const ids=data.ids.slice(offset,offset+90); if(!ids.length) continue;
      const result=await env.DB.prepare(`SELECT r.*,u.initials FROM records r JOIN users u ON u.id=r.user_id WHERE r.id IN (${ids.map(()=>'?').join(',')})`).bind(...ids).all();
      rows.push(...(result.results||[]));
    }
    const safe=value=>{const result=String(value??'');return /^[=+\-@\t\r\n]/.test(result)?`'${result}`:result};
    const quote=value=>`"${safe(value).replace(/"/g,'""')}"`;
    const columns=['date','kind','market','initials','category','order_no','model','phone','customer','content','answer','code','logistics','completed'];
    const csv=['등록일,구분,마켓,담당자,카테고리,주문번호,모델명,연락처,고객명,내용,답변,반품코드,물류번호,반품완료일,다운로드 담당자',...rows.map(row=>[...columns.map(key=>quote(row[key])),quote(user.initials)].join(','))].join('\r\n');
    await env.DB.prepare('INSERT INTO audit(user_id,action,created) VALUES(?,?,?)').bind(user.id,'다운로드',now()).run();
    return json({csv:`\ufeff${csv}`});
  }
  return error('지원하지 않는 요청입니다.',404);
}

export default {
  async fetch(request, env) {
    try {
      const url = new URL(request.url);
      if (url.pathname === '/robots.txt') return secure(new Response('User-agent: *\nDisallow: /\n',{headers:{'Content-Type':'text/plain; charset=utf-8'}}));
      if (url.pathname.startsWith('/api/')) {
        if (request.method === 'GET') return await getApi(request,env,url.pathname);
        if (request.method === 'POST') return await postApi(request,env,url.pathname);
        return error('지원하지 않는 요청입니다.',405);
      }
      return secure(await env.ASSETS.fetch(request));
    } catch (cause) {
      const raw = cause?.message || '';
      const message = cause instanceof SyntaxError
        ? '올바른 요청 형식을 사용하세요.'
        : (/^[가-힣]/.test(raw) ? raw : '요청을 처리하지 못했습니다.');
      console.error('request_failed', cause?.name || 'Error');
      return error(message,400);
    }
  }
};
