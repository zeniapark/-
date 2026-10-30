let adminMode=false;
function exitAdminMode(){
    adminMode=false;
    $('#admin-page').hidden=true;
    document.querySelector('main > .page').hidden=false;
    $('#admin-toggle').textContent='관리자 모드';
    document.querySelectorAll('[data-tab]').forEach(b=>b.classList.toggle('active',b.dataset.tab===tab));
    $('#invite-result').hidden=true;
    $('#invite-link').value='';
}
function sessionRoleChanged(){
    exitAdminMode();
    $('#admin-toggle').hidden=!user?.is_admin;
    $('#role-label').textContent=user?(user.is_admin?'관리자':'사용자'):'';
    if(!user){$('#members').innerHTML='';$('#invitations').innerHTML=''}
}
window.addEventListener('cs-session',sessionRoleChanged);
sessionRoleChanged();
async function loadAdmin(){
    if(!user?.is_admin)return;
    $('#admin-error').textContent='';
    try{
        const [members,invitations]=await Promise.all([api('users'),api('invitations')]);
        if(!adminMode)return;
        $('#member-count').textContent=`총 ${members.length}명`;
        $('#members').innerHTML=members.map(m=>`<tr><td>${escape(m.initials)}</td><td>${escape(m.email)}</td><td><span class="badge">${m.is_admin?'관리자':'사용자'}</span></td><td>${m.approved?'이용 가능':'접근 제한 / 승인 대기'}</td><td>${m.id===user.id?'현재 계정':`<button type="button" data-member="${m.id}" data-allow="${m.approved?'0':'1'}">${m.approved?'접근 차단':'가입 승인'}</button>`}</td></tr>`).join('');
        $('#invitations').innerHTML=invitations.length?invitations.map(i=>{const pending=!i.used_at&&!i.revoked_at&&new Date(i.expires)>new Date();return `<tr><td>${escape(i.email)}</td><td>${escape(new Date(i.expires).toLocaleString('ko-KR',{timeZone:'Asia/Seoul'}))}</td><td>${i.revoked_at?'취소':i.used_at?'사용 완료':pending?'가입 대기':'만료'}</td><td>${pending?`<button type="button" data-revoke="${i.id}">초대 취소</button>`:'—'}</td></tr>`}).join(''):'<tr><td colspan="4" class="empty">발급한 초대가 없습니다.</td></tr>';
    }catch(e){$('#admin-error').textContent=e.message}
}
$('#admin-toggle').onclick=async()=>{
    if(!user?.is_admin)return;
    if(adminMode){exitAdminMode();$('#crumb').textContent=tab;return}
    adminMode=true;
    $('#admin-page').hidden=false;
    document.querySelector('main > .page').hidden=true;
    $('#admin-toggle').textContent='사용자 모드';
    $('#crumb').textContent='관리자 모드';
    document.querySelectorAll('[data-tab]').forEach(b=>b.classList.remove('active'));
    await loadAdmin();
};
$('#admin-refresh').onclick=loadAdmin;
$('#invite-form').onsubmit=async e=>{
    e.preventDefault();
    $('#admin-error').textContent='';
    const button=e.target.querySelector('button');button.disabled=true;
    try{
        const invitation=await api('invitations',{email:new FormData(e.target).get('email')});
        $('#invite-link').value=location.origin+'/#'+new URLSearchParams({invite:invitation.invitation_token,email:invitation.email});
        $('#invite-result').hidden=false;
        e.target.reset();
        await loadAdmin();
    }catch(err){$('#admin-error').textContent=err.message}finally{button.disabled=false}
};
$('#copy-invite').onclick=async()=>{
    try{await navigator.clipboard.writeText($('#invite-link').value);toast('초대 링크가 복사되었습니다. 담당자에게 직접 전달하세요.')}
    catch{$('#invite-link').select();toast('링크를 선택했습니다. 복사해 주세요.')}
};
$('#members').onclick=async e=>{
    const button=e.target.closest('[data-member]');if(!button)return;
    button.disabled=true;
    try{await api('users/access',{id:Number(button.dataset.member),approved:button.dataset.allow==='1'});await loadAdmin();toast('회원 접근 권한이 변경되었습니다.')}
    catch(err){$('#admin-error').textContent=err.message;button.disabled=false}
};
$('#invitations').onclick=async e=>{
    const button=e.target.closest('[data-revoke]');if(!button)return;
    button.disabled=true;
    try{await api('invitations/revoke',{id:Number(button.dataset.revoke)});$('#invite-link').value='';$('#invite-result').hidden=true;await loadAdmin();toast('초대가 취소되었습니다.')}
    catch(err){$('#admin-error').textContent=err.message;button.disabled=false}
};
