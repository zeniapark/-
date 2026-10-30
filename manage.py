"""Local operator commands. Invitation tokens are printed only on explicit invocation."""
import argparse
import json
from app import initialize, connect, create_invitation, normalize_email


def main():
    parser=argparse.ArgumentParser(description='HANARO CS Insight 회원 접근 관리')
    commands=parser.add_subparsers(dest='command',required=True)
    for name,help_text in [('invite','새 이메일에 일회용 초대 발급'),('approve','기존 계정 승인')]:
        command=commands.add_parser(name,help=help_text)
        command.add_argument('email',help='초대하거나 승인할 정확한 이메일')
        command.add_argument('--admin',action='store_true',help='관리자 권한 부여')
    args=parser.parse_args()
    try:
        email=normalize_email(args.email)
        initialize()
        with connect() as c:
            if args.command=='invite':
                result=create_invitation(c,email,is_admin=args.admin)
            else:
                c.execute('BEGIN IMMEDIATE')
                row=c.execute('SELECT id FROM users WHERE email=?',(email,)).fetchone()
                if not row: raise ValueError('기존 계정을 찾을 수 없습니다. 신규 회원은 invite 명령을 사용하세요.')
                c.execute('UPDATE users SET approved=1,is_admin=CASE WHEN ? THEN 1 ELSE is_admin END WHERE id=?',(int(args.admin),row['id']))
                result={'ok':True,'email':email}
        print(json.dumps(result,ensure_ascii=False))
    except ValueError as exc:
        parser.exit(1,str(exc)+'\n')


if __name__=='__main__': main()
