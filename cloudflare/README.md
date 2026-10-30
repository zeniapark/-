# HANARO Cloudflare 배포판

이 폴더는 회사 PC가 꺼져 있어도 고정 `workers.dev` 주소에서 실행되는 버전입니다. 화면은 상위 `static` 폴더를 그대로 사용하고, 회원·상담 기록은 Cloudflare D1에 누적합니다.

## 1. 무료 계정 연결

Cloudflare 계정을 만든 뒤 이 폴더에서 실행합니다.

```sh
npm install
npx wrangler login
```

브라우저에서 Cloudflare 접근을 승인합니다. 비밀번호나 인증키를 소스 또는 채팅에 입력하지 않습니다.

## 2. 데이터베이스 생성

```sh
npx wrangler d1 create hanaro-cs-insight-db
```

출력된 `database_id`를 `wrangler.jsonc`의 `00000000-0000-0000-0000-000000000000` 대신 입력합니다. 이어서 원격 DB 구조를 만듭니다.

```sh
npm run db:remote
```

## 3. 사이트 게시

```sh
npm run deploy
```

명령 끝에 표시되는 `https://hanaro-cs-insight.<계정>.workers.dev`가 고정 접속 주소입니다.

## 4. 첫 관리자 초대

사이트 주소와 관리자 이메일을 넣습니다.

```sh
node scripts/create-admin-invite.mjs zeniapark0907@gmail.com https://hanaro-cs-insight.<계정>.workers.dev
```

출력의 `signup_url`을 본인 브라우저에서 열어 비밀번호와 이니셜을 설정합니다. 초대 토큰은 공개하거나 저장소에 올리지 않습니다. 가입 후 관리자 화면에서 13명의 이메일별 초대 링크를 동시에 생성할 수 있습니다.

## 로컬 검증

```sh
npm test
```

테스트는 임시 로컬 D1만 사용하며 실제 데이터에는 접근하지 않습니다.

## 회사 계정으로 이전

소스 저장소를 회사 GitHub 조직으로 이전하고, D1 데이터를 내보낸 뒤 회사 Cloudflare 계정의 새 D1으로 가져와 재배포합니다. 회사 관리자 두 명 이상에게 GitHub와 Cloudflare 권한을 부여한 후 개인 계정을 제거합니다. 무료 한도와 정책은 Cloudflare 정책 변경 및 사용량에 따라 달라질 수 있습니다.
