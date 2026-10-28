PASSWORD = 'R22Pass#2024'

ROLE_TO_TABLE = {
    'admin': 'app01_admin',
    'teacher': 'app01_teacher',
    'student': 'app01_student',
}


def make_account(login_name='T100001', person_type='teacher', is_active=True,
                 must_change=False):
    from r21_account.models import Account

    account = Account.objects.create_user(
        login_name, PASSWORD, display_name='账号{}'.format(login_name),
        person_type=person_type, is_active=is_active,
    )
    account.must_change_password = must_change
    account.save(update_fields=['must_change_password'])
    return account


def link_legacy(account, role='teacher', legacy_id=None):
    from r21_account.models import LegacyAccountLink

    return LegacyAccountLink.objects.create(
        account=account,
        source_table=ROLE_TO_TABLE[role],
        source_pk=str(legacy_id if legacy_id is not None else account.login_name),
    )


def login_account(client, login_name, password=PASSWORD):
    return client.post(
        '/r21/login/', {'login_name': login_name, 'password': password}
    )


def set_legacy_session(client, role, legacy_id, name='legacy'):
    session = client.session
    session['info'] = {'id': str(legacy_id), 'type': role, 'name': name}
    session.save()


def identity_payload(client):
    resp = client.get('/identity/')
    return resp.status_code, resp.json()['identity']
