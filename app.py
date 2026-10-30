import csv, hashlib, hmac, io, ipaddress, json, os, re, secrets, sqlite3, threading, time
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from http.cookies import SimpleCookie
from pathlib import Path

ROOT = Path(__file__).parent
DB = Path(os.environ.get('CS_DB', ROOT / 'data' / 'cs.sqlite3'))
MARKETS = ['네이버','11번가','G마켓','옥션','오늘의집','쿠팡','카카오','롯데온','SSG','알리','컬리','자사몰','토스']
CATEGORIES = ['배송요청사항','제품','구매','반품','상품권','컴플레인','기타']
RETURNS = ['배송일정','설치불가','제품불량','단순변심','서비스불만','기타']
KINDS = ['문의글','유선','반품','VOC','CS매뉴얼']
AUTH_WINDOW_SECONDS = 15 * 60
AUTH_MAX_FAILURES = 10
AUTH_FAILURES = {}
AUTH_FAILURES_LOCK = threading.Lock()


def auth_is_limited(key):
    cutoff = time.monotonic() - AUTH_WINDOW_SECONDS
    with AUTH_FAILURES_LOCK:
        attempts = [stamp for stamp in AUTH_FAILURES.get(key, []) if stamp > cutoff]
        if attempts:
            AUTH_FAILURES[key] = attempts
        else:
            AUTH_FAILURES.pop(key, None)
        return len(attempts) >= AUTH_MAX_FAILURES


def auth_failed(key):
    with AUTH_FAILURES_LOCK:
        AUTH_FAILURES.setdefault(key, []).append(time.monotonic())


def auth_succeeded(key):
    with AUTH_FAILURES_LOCK:
        AUTH_FAILURES.pop(key, None)
def connect():
    c = sqlite3.connect(DB); c.row_factory = sqlite3.Row; return c
def initialize():
    DB.parent.mkdir(parents=True, exist_ok=True)
    with connect() as c:
        c.executescript('''CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY,email TEXT UNIQUE NOT NULL,initials TEXT NOT NULL,salt TEXT NOT NULL,password TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY,user_id INTEGER,expires TEXT);
CREATE TABLE IF NOT EXISTS records(id INTEGER PRIMARY KEY,kind TEXT NOT NULL,date TEXT NOT NULL,market TEXT,category TEXT,order_no TEXT,model TEXT,phone TEXT,customer TEXT,content TEXT,answer TEXT,code TEXT,logistics TEXT,completed TEXT,after_ship INTEGER DEFAULT 0,user_id INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY,user_id INTEGER,action TEXT,created TEXT);''')
        columns={row['name'] for row in c.execute('PRAGMA table_info(users)')}
        for name in ('is_admin','approved'):
            if name not in columns:
                c.execute(f'ALTER TABLE users ADD COLUMN {name} INTEGER NOT NULL DEFAULT 0')
        c.execute('''CREATE TABLE IF NOT EXISTS invitations(
            id INTEGER PRIMARY KEY,token_hash TEXT UNIQUE NOT NULL,email TEXT NOT NULL,
            expires TEXT NOT NULL,is_admin INTEGER NOT NULL DEFAULT 0,
            used_at TEXT,revoked_at TEXT,created_by INTEGER)''')
def hash_password(p,s): return hashlib.scrypt(p.encode(),salt=bytes.fromhex(s),n=16384,r=8,p=1).hex()
def today(): return datetime.now(timezone(timedelta(hours=9))).date().isoformat()
def normalize_email(value):
    email=str(value or '').strip().lower()
    if len(email)>254 or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',email):
        raise ValueError('올바른 이메일 주소를 입력하세요.')
    return email
def invitation_hash(token): return hashlib.sha256(token.encode()).hexdigest()
def create_invitation(c,email,is_admin=False,created_by=None):
    email=normalize_email(email)
    if c.execute('SELECT 1 FROM users WHERE email=?',(email,)).fetchone():
        raise ValueError('이미 가입된 이메일입니다. 기존 계정은 운영자가 승인할 수 있습니다.')
    token=secrets.token_urlsafe(32)
    expires=(datetime.now(timezone.utc)+timedelta(days=7)).isoformat()
    c.execute('INSERT INTO invitations(token_hash,email,expires,is_admin,created_by) VALUES(?,?,?,?,?)',
              (invitation_hash(token),email,expires,int(bool(is_admin)),created_by))
    return {'invitation_token':token,'email':email,'expires':expires}
class Handler(BaseHTTPRequestHandler):
    def end_headers(self):
        self.send_header('X-Robots-Tag','noindex, nofollow, noarchive')
        self.send_header('Referrer-Policy','no-referrer')
        self.send_header('X-Frame-Options','DENY')
        self.send_header('Permissions-Policy','camera=(), microphone=(), geolocation=()')
        self.send_header('Content-Security-Policy',"default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        super().end_headers()

    def auth_key(self):
        address = self.client_address[0]
        if address in ('127.0.0.1','::1'):
            forwarded = self.headers.get('CF-Connecting-IP','').strip()
            try:
                if forwarded:
                    address = str(ipaddress.ip_address(forwarded))
            except ValueError:
                pass
        return address
    def log_request(self,code='-',size='-'):
        # Never include URL query parameters or invitation material in access logs.
        self.log_message('%s %s %s',self.command,self.path.split('?',1)[0].split('#',1)[0],str(code))
    def reply(self, status, data, headers=None):
        body=json.dumps(data,ensure_ascii=False).encode(); self.send_response(status)
        self.send_header('Content-Type','application/json; charset=utf-8')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Cache-Control','no-store')
        for k,v in (headers or {}).items(): self.send_header(k,v)
        self.end_headers(); self.wfile.write(body)
    def user(self,c):
        cookie=SimpleCookie()
        try: cookie.load(self.headers.get('Cookie',''))
        except Exception: return None
        token=cookie.get('session')
        if not token: return None
        return c.execute('SELECT u.id,u.email,u.initials,u.is_admin FROM users u JOIN sessions s ON s.user_id=u.id WHERE s.token=? AND s.expires>? AND u.approved=1',(token.value,datetime.now(timezone.utc).isoformat())).fetchone()
    def do_GET(self):
        if self.path=='/robots.txt':
            self.send_response(200); self.send_header('Content-Type','text/plain; charset=utf-8')
            self.end_headers(); self.wfile.write(b'User-agent: *\nDisallow: /\n'); return
        if self.path=='/api/me':
            with connect() as c:
                u=self.user(c); self.reply(200,{'user':dict(u) if u else None,'today':today(),'markets':MARKETS,'categories':CATEGORIES,'returns':RETURNS})
            return
        if self.path=='/api/invitations':
            with connect() as c:
                u=self.user(c)
                if not u: return self.reply(401,{'error':'로그인이 필요합니다.'})
                if not u['is_admin']: return self.reply(403,{'error':'관리자만 초대를 관리할 수 있습니다.'})
                rows=c.execute('SELECT id,email,expires,is_admin,used_at,revoked_at FROM invitations ORDER BY id DESC').fetchall()
                self.reply(200,[dict(row) for row in rows])
            return
        if self.path=='/api/users':
            with connect() as c:
                u=self.user(c)
                if not u: return self.reply(401,{'error':'로그인이 필요합니다.'})
                if not u['is_admin']: return self.reply(403,{'error':'관리자만 회원을 관리할 수 있습니다.'})
                rows=c.execute('SELECT id,email,initials,is_admin,approved FROM users ORDER BY id').fetchall()
                self.reply(200,[dict(row) for row in rows])
            return
        if self.path=='/api/records':
            with connect() as c:
                if not self.user(c): return self.reply(401,{'error':'로그인이 필요합니다.'})
                rows=c.execute('SELECT r.*,u.initials,u.email FROM records r JOIN users u ON u.id=r.user_id ORDER BY date DESC,r.id DESC').fetchall()
                self.reply(200,[dict(r) for r in rows])
            return
        file=ROOT/'static'/('index.html' if self.path=='/' else self.path.lstrip('/'))
        if file.parent.resolve()!=(ROOT/'static').resolve() or not file.is_file(): return self.reply(404,{'error':'페이지가 없습니다.'})
        self.send_response(200); self.send_header('Content-Type',{'html':'text/html; charset=utf-8','js':'text/javascript; charset=utf-8','css':'text/css; charset=utf-8'}.get(file.suffix[1:],'text/plain')); self.end_headers(); self.wfile.write(file.read_bytes())
    def do_POST(self):
        if self.headers.get('Sec-Fetch-Site')=='cross-site': return self.reply(403,{'error':'허용되지 않은 요청입니다.'})
        try:
            length=int(self.headers.get('Content-Length',0))
            if length<0 or length>1000000: return self.reply(413,{'error':'요청이 너무 큽니다.'})
            d=json.loads(self.rfile.read(length))
            if not isinstance(d,dict): raise ValueError('올바른 요청 형식을 사용하세요.')
            with connect() as c:
                if self.path in ['/api/signup','/api/login']:
                    auth_key=self.auth_key()
                    if auth_is_limited(auth_key):
                        return self.reply(429,{'error':'로그인 시도가 너무 많습니다. 15분 뒤 다시 시도하세요.'})
                    email=str(d.get('email','')).strip().lower(); password=str(d.get('password',''))
                    if self.path=='/api/signup':
                        initials=str(d.get('initials','')).strip()
                        email=normalize_email(email)
                        if not (8<=len(password)<=15 and re.search('[a-zA-Z]',password) and re.search('[0-9]',password) and re.search(r'[^a-zA-Z0-9\s]',password) and not re.search(r'\s',password)): raise ValueError('비밀번호는 영문·숫자·특수문자를 포함한 8~15자입니다.')
                        if not initials or len(initials)>12: raise ValueError('담당자 이니셜을 12자 이내로 입력하세요.')
                        invite_token=str(d.get('invitation_token',''))
                        if not (20<=len(invite_token)<=200):
                            auth_failed(auth_key)
                            return self.reply(403,{'error':'유효한 초대 링크로 가입해 주세요.'})
                        # Serialize invitation validation and consumption with user creation.
                        c.execute('BEGIN IMMEDIATE')
                        now=datetime.now(timezone.utc).isoformat()
                        invitation=c.execute('SELECT * FROM invitations WHERE token_hash=? AND email=? AND expires>? AND used_at IS NULL AND revoked_at IS NULL',
                                             (invitation_hash(invite_token),email,now)).fetchone()
                        if not invitation:
                            auth_failed(auth_key)
                            return self.reply(403,{'error':'초대가 유효하지 않거나 만료되었습니다. 초대받은 이메일을 확인하세요.'})
                        salt=secrets.token_hex(16)
                        try: c.execute('INSERT INTO users(email,initials,salt,password,is_admin,approved) VALUES(?,?,?,?,?,1)',(email,initials,salt,hash_password(password,salt),invitation['is_admin']))
                        except sqlite3.IntegrityError: raise ValueError('이미 가입된 이메일입니다.')
                        c.execute('UPDATE invitations SET used_at=? WHERE id=?',(now,invitation['id']))
                    u=c.execute('SELECT * FROM users WHERE email=?',(email,)).fetchone()
                    if not u or not hmac.compare_digest(u['password'],hash_password(password,u['salt'])):
                        auth_failed(auth_key)
                        return self.reply(401,{'error':'이메일 또는 비밀번호를 확인하세요.'})
                    if not u['approved']:
                        auth_failed(auth_key)
                        return self.reply(403,{'error':'관리자 승인이 필요한 계정입니다. 운영자에게 문의하세요.'})
                    auth_succeeded(auth_key)
                    token=secrets.token_urlsafe(32); c.execute('INSERT INTO sessions VALUES(?,?,?)',(token,u['id'],(datetime.now(timezone.utc)+timedelta(days=7)).isoformat()))
                    return self.reply(200,{'ok':True},{'Set-Cookie':f'session={token}; HttpOnly; SameSite=Lax; Path=/; Max-Age=604800'+('; Secure' if os.environ.get('CS_SECURE_COOKIE')=='1' else '')})
                u=self.user(c)
                if not u: return self.reply(401,{'error':'로그인이 필요합니다.'})
                if self.path=='/api/users/access':
                    if not u['is_admin']: return self.reply(403,{'error':'관리자만 회원을 관리할 수 있습니다.'})
                    user_id=d.get('id'); approved=d.get('approved')
                    if not isinstance(user_id,int) or isinstance(user_id,bool) or not isinstance(approved,bool):
                        raise ValueError('회원 번호와 승인 여부를 확인하세요.')
                    if user_id==u['id'] and not approved: return self.reply(400,{'error':'자신의 접근 권한을 차단할 수 없습니다.'})
                    c.execute('BEGIN IMMEDIATE')
                    target=c.execute('SELECT id,is_admin,approved FROM users WHERE id=?',(user_id,)).fetchone()
                    if not target: return self.reply(404,{'error':'회원을 찾을 수 없습니다.'})
                    if not approved and target['is_admin'] and target['approved']:
                        admin_count=c.execute('SELECT COUNT(*) FROM users WHERE is_admin=1 AND approved=1').fetchone()[0]
                        if admin_count<=1: return self.reply(400,{'error':'마지막 관리자를 차단할 수 없습니다.'})
                    c.execute('UPDATE users SET approved=? WHERE id=?',(int(approved),user_id))
                    if not approved: c.execute('DELETE FROM sessions WHERE user_id=?',(user_id,))
                    c.execute('INSERT INTO audit(user_id,action,created) VALUES(?,?,?)',(u['id'],f'회원 {user_id} '+('승인' if approved else '차단'),datetime.now(timezone.utc).isoformat()))
                    return self.reply(200,{'ok':True})
                if self.path in ['/api/invitations','/api/invitations/revoke']:
                    if not u['is_admin']: return self.reply(403,{'error':'관리자만 초대를 관리할 수 있습니다.'})
                    if self.path=='/api/invitations':
                        invitation=create_invitation(c,d.get('email'),created_by=u['id'])
                        c.execute('INSERT INTO audit(user_id,action,created) VALUES(?,?,?)',(u['id'],'회원 초대',datetime.now(timezone.utc).isoformat()))
                        return self.reply(201,invitation)
                    invite_id=d.get('id')
                    if not isinstance(invite_id,int) or isinstance(invite_id,bool): raise ValueError('초대 번호를 확인하세요.')
                    result=c.execute('UPDATE invitations SET revoked_at=? WHERE id=? AND used_at IS NULL AND revoked_at IS NULL',(datetime.now(timezone.utc).isoformat(),invite_id))
                    if not result.rowcount: return self.reply(404,{'error':'취소할 수 있는 초대가 없습니다.'})
                    return self.reply(200,{'ok':True})
                if self.path=='/api/logout':
                    cookie=SimpleCookie(self.headers.get('Cookie','')); c.execute('DELETE FROM sessions WHERE token=?',(cookie['session'].value,))
                    return self.reply(200,{'ok':True},{'Set-Cookie':'session=; HttpOnly; SameSite=Lax; Path=/; Max-Age=0'})
                if self.path=='/api/records':
                    kind=d.get('kind'); category=d.get('category')
                    if kind not in KINDS: raise ValueError('등록 구분을 확인하세요.')
                    if category not in (RETURNS if kind=='반품' else CATEGORIES): raise ValueError('카테고리를 확인하세요.')
                    if kind=='반품' and (not str(d.get('order_no','')).strip() or not str(d.get('customer','')).strip() or not d.get('completed')): raise ValueError('주문번호, 고객명, 반품완료일을 입력하세요.')
                    if kind=='유선' and not str(d.get('phone','')).strip(): raise ValueError('전화번호를 입력하세요.')
                    if d.get('market') not in MARKETS: raise ValueError('마켓을 선택하세요.')
                    if kind=='반품' and d.get('code') not in ['일반반품','착하반품','영업반품']: raise ValueError('반품 코드를 선택하세요.')
                    for key in ['date','completed']:
                        if d.get(key): datetime.strptime(d[key],'%Y-%m-%d')
                    if not d.get('date') or not str(d.get('content','')).strip(): raise ValueError('등록일과 내용을 입력하세요.')
                    fields=['kind','date','market','category','order_no','model','phone','customer','content','answer','code','logistics','completed']
                    values=[str(d.get(k,'')).strip() for k in fields]
                    c.execute('INSERT INTO records('+','.join(fields)+',after_ship,user_id) VALUES('+','.join('?' for _ in range(15))+')',values+[int(kind=='반품' and bool(d.get('after_ship'))),u['id']])
                    c.execute('INSERT INTO audit(user_id,action,created) VALUES(?,?,?)',(u['id'],'등록',datetime.now(timezone.utc).isoformat()))
                    return self.reply(201,{'ok':True})
                if self.path=='/api/export':
                    ids=d.get('ids',[])
                    if not isinstance(ids,list) or len(ids)>10000: raise ValueError('다운로드 범위를 확인하세요.')
                    rows=c.execute('SELECT r.*,u.initials FROM records r JOIN users u ON u.id=r.user_id WHERE r.id IN ('+','.join('?' for _ in ids)+')',ids).fetchall() if ids else []
                    out=io.StringIO(); w=csv.writer(out); w.writerow(['등록일','구분','마켓','담당자','카테고리','주문번호','모델명','연락처','고객명','내용','답변','반품코드','물류번호','반품완료일','다운로드 담당자'])
                    def safe(v):
                        v=str(v or ''); return "'"+v if v.startswith(('=','+','-','@','\t','\r','\n')) else v
                    for r in rows: w.writerow([safe(r[k]) for k in ['date','kind','market','initials','category','order_no','model','phone','customer','content','answer','code','logistics','completed']]+[safe(u['initials'])])
                    c.execute('INSERT INTO audit(user_id,action,created) VALUES(?,?,?)',(u['id'],'다운로드',datetime.now(timezone.utc).isoformat()))
                    return self.reply(200,{'csv':'\ufeff'+out.getvalue()})
                self.reply(404,{'error':'지원하지 않는 요청입니다.'})
        except (ValueError,TypeError) as e: self.reply(400,{'error':str(e)})
if __name__=='__main__':
    initialize(); ThreadingHTTPServer(('0.0.0.0',int(os.environ.get('PORT','3000'))),Handler).serve_forever()
