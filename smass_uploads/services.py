"""S14 服务层：上传校验、私有存储、归属鉴权与删除。

校验顺序（任一失败即拒绝，不落盘）：
1. 用途合法；
2. 扩展名在白名单内；
3. 文件大小不超过上限；
4. 文件签名匹配扩展名（CSV 走文本校验）；
5. ZIP 类文件通过解压炸弹检查。

落盘后计算 SHA-256，文件名统一为 UUID + 原扩展名，原始文件名只存数据库。
"""
from __future__ import annotations

import hashlib
import io
import logging
import os
import re
import uuid
import zipfile

from django.conf import settings

from r21_account import authorization as authz
from r21_account.models import RoleCode

from .models import (
    FILE_STATUS,
    PURPOSE_ATTACHMENT,
    PURPOSE_AVATAR,
    PURPOSE_IMPORT,
    PURPOSE_REPORT,
    PURPOSES,
    STATUS_DELETED,
    STATUS_READY,
    UploadedFile,
)

logger = logging.getLogger('smass.audit')

#: 单文件上限 10 MB
MAX_BYTES = 10 * 1024 * 1024
#: ZIP 条目上限
MAX_ZIP_ENTRIES = 200
#: ZIP 解压后总大小上限 50 MB
MAX_ZIP_UNCOMPRESSED = 50 * 1024 * 1024
#: 压缩比上限（解压后 / 压缩后）
MAX_COMPRESSION_RATIO = 100

ALLOWED_EXTENSIONS = {
    PURPOSE_AVATAR: {'.png', '.jpg', '.jpeg'},
    PURPOSE_ATTACHMENT: {'.pdf', '.png', '.jpg', '.jpeg', '.docx', '.xlsx', '.zip'},
    PURPOSE_IMPORT: {'.csv', '.xlsx'},
    PURPOSE_REPORT: {'.pdf', '.csv'},
}

SIGNATURES = {
    '.png': (b'\x89PNG\r\n\x1a\n',),
    '.jpg': (b'\xff\xd8\xff',),
    '.jpeg': (b'\xff\xd8\xff',),
    '.pdf': (b'%PDF-',),
    '.zip': (b'PK\x03\x04', b'PK\x05\x06', b'PK\x07\x08'),
    '.docx': (b'PK\x03\x04',),
    '.xlsx': (b'PK\x03\x04',),
}

ZIP_EXTENSIONS = {'.zip', '.docx', '.xlsx'}
TEXT_EXTENSIONS = {'.csv'}

_UNSAFE_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')

ADMIN_ROLES = frozenset({RoleCode.SYSTEM_ADMIN, RoleCode.COLLEGE_ADMIN})


class UploadError(ValueError):
    def __init__(self, message, code='UPLOAD_ERROR'):
        self.code = code
        super().__init__(message)


class PermissionDenied(UploadError):
    def __init__(self, message='当前账号没有该操作权限'):
        super().__init__(message, code='PERMISSION_DENIED')


def can_manage(account):
    roles = authz.active_roles(account)
    if not roles:
        return False
    if set(roles) & ADMIN_ROLES:
        return True
    return authz.has_action(account, 'manage_roles')


def private_root():
    root = getattr(settings, 'SMASS_PRIVATE_MEDIA_ROOT', None)
    if root:
        return str(root)
    return os.path.join(str(settings.BASE_DIR), 'private_uploads')


def sanitize_filename(raw):
    """只保留 basename，去掉控制字符与路径分隔符，限制长度。"""
    name = os.path.basename(str(raw or '').replace('\\', '/'))
    name = _UNSAFE_CHARS.sub('_', name).strip(' .')
    if not name:
        name = 'upload.bin'
    stem, ext = os.path.splitext(name)
    stem = stem[:100] or 'upload'
    return '{}{}'.format(stem, ext[:16])


def extension_of(name):
    return os.path.splitext(str(name or ''))[1].lower()


def _read_head(file_obj, size=16):
    file_obj.seek(0)
    head = file_obj.read(size)
    file_obj.seek(0)
    return head


def _check_signature(file_obj, ext):
    if ext in TEXT_EXTENSIONS:
        file_obj.seek(0)
        sample = file_obj.read(4096)
        file_obj.seek(0)
        if b'\x00' in sample:
            raise UploadError('文件内容包含二进制数据，与扩展名不符', code='BAD_SIGNATURE')
        try:
            sample.decode('utf-8')
        except UnicodeDecodeError:
            # 允许 GBK 编码的 CSV
            try:
                sample.decode('gbk')
            except UnicodeDecodeError:
                raise UploadError('文件编码无法识别（需 UTF-8 或 GBK）',
                                  code='BAD_ENCODING')
        return 'text'

    expected = SIGNATURES.get(ext)
    if not expected:
        raise UploadError('该扩展名不支持签名校验', code='UNSUPPORTED_EXTENSION')
    head = _read_head(file_obj, max(len(sig) for sig in expected))
    if not any(head.startswith(sig) for sig in expected):
        raise UploadError('文件签名与扩展名不符（疑似改扩展名）', code='BAD_SIGNATURE')
    return 'signature'


def _check_zip(file_obj):
    file_obj.seek(0)
    try:
        with zipfile.ZipFile(file_obj) as archive:
            infos = archive.infolist()
            if len(infos) > MAX_ZIP_ENTRIES:
                raise UploadError('压缩包条目过多（{}）'.format(len(infos)),
                                  code='ZIP_TOO_MANY_ENTRIES')
            total_uncompressed = sum(info.file_size for info in infos)
            if total_uncompressed > MAX_ZIP_UNCOMPRESSED:
                raise UploadError('压缩包解压后过大（{} 字节）'.format(total_uncompressed),
                                  code='ZIP_TOO_LARGE')
            for info in infos:
                if info.compress_size > 0:
                    ratio = info.file_size / info.compress_size
                    if ratio > MAX_COMPRESSION_RATIO:
                        raise UploadError('压缩比异常（{}:1），疑似解压炸弹'.format(int(ratio)),
                                          code='ZIP_BOMB')
    except zipfile.BadZipFile:
        raise UploadError('压缩包格式损坏', code='BAD_ZIP')
    finally:
        file_obj.seek(0)


def validate(file_obj, purpose, original_name=None):
    if purpose not in dict(PURPOSES):
        raise UploadError('未知的上传用途', code='BAD_PURPOSE')
    name = sanitize_filename(original_name or getattr(file_obj, 'name', ''))
    ext = extension_of(name)
    allowed = ALLOWED_EXTENSIONS.get(purpose, set())
    if ext not in allowed:
        raise UploadError(
            '用途 {} 不允许上传 {} 类型'.format(purpose, ext or '（无扩展名）'),
            code='EXTENSION_NOT_ALLOWED')

    size = getattr(file_obj, 'size', None)
    if size is None:
        file_obj.seek(0, os.SEEK_END)
        size = file_obj.tell()
        file_obj.seek(0)
    if size <= 0:
        raise UploadError('空文件不允许上传', code='EMPTY_FILE')
    if size > MAX_BYTES:
        raise UploadError('文件超过上限 {} 字节'.format(MAX_BYTES), code='FILE_TOO_LARGE')

    kind = _check_signature(file_obj, ext)
    if ext in ZIP_EXTENSIONS:
        _check_zip(file_obj)
        kind = 'zip'

    return {
        'name': name,
        'extension': ext,
        'size': int(size),
        'check': kind,
        'purpose': purpose,
    }


def _sha256(file_obj):
    digest = hashlib.sha256()
    file_obj.seek(0)
    for chunk in iter(lambda: file_obj.read(1024 * 1024), b''):
        digest.update(chunk)
    file_obj.seek(0)
    return digest.hexdigest()


def store(file_obj, owner, purpose, *, declared_type=''):
    """校验并保存到私有目录，返回 ``UploadedFile``。"""
    if getattr(owner, 'pk', None) is None:
        raise UploadError('请先登录', code='NOT_AUTHENTICATED')
    meta = validate(file_obj, purpose)
    digest = _sha256(file_obj)

    stored_name = '{}{}'.format(uuid.uuid4().hex, meta['extension'])
    root = private_root()
    folder = os.path.join(root, purpose)
    os.makedirs(folder, exist_ok=True)
    target = os.path.join(folder, stored_name)

    file_obj.seek(0)
    with open(target, 'wb') as handle:
        for chunk in iter(lambda: file_obj.read(1024 * 1024), b''):
            handle.write(chunk)

    upload = UploadedFile.objects.create(
        owner=owner, purpose=purpose,
        original_name=meta['name'][:255],
        stored_name=stored_name,
        content_type=str(declared_type or '')[:100],
        size=meta['size'], sha256=digest, status=STATUS_READY,
        meta={'check': meta['check'], 'extension': meta['extension'],
              'virus_scan': 'not_available'})

    logger.info('upload_stored id=%s purpose=%s size=%s owner=%s',
                upload.pk, purpose, meta['size'], owner.pk)
    return upload


def path_for(upload):
    root = private_root()
    return os.path.join(root, upload.purpose, upload.stored_name)


def can_access(upload, account):
    if getattr(account, 'pk', None) is None:
        return False
    if str(upload.owner_id) == str(account.pk):
        return True
    return can_manage(account)


def open_upload(upload, account):
    """鉴权后返回文件句柄。"""
    if upload.status == STATUS_DELETED:
        raise UploadError('文件已删除', code='FILE_DELETED')
    if not can_access(upload, account):
        raise PermissionDenied('只能下载自己的文件')
    path = path_for(upload)
    if not os.path.exists(path):
        raise UploadError('文件不存在于存储', code='FILE_MISSING')
    logger.info('upload_downloaded id=%s account=%s', upload.pk, getattr(account, 'pk', '-'))
    return open(path, 'rb')


def delete_upload(upload, account):
    if not can_access(upload, account):
        raise PermissionDenied('只能删除自己的文件')
    if upload.status == STATUS_DELETED:
        raise UploadError('文件已删除', code='BAD_STATE')

    path = path_for(upload)
    if os.path.exists(path):
        os.remove(path)
    upload.status = STATUS_DELETED
    upload.save(update_fields=['status'])
    logger.info('upload_deleted id=%s account=%s', upload.pk, getattr(account, 'pk', '-'))
    return upload


def scoped_files(account):
    qs = UploadedFile.objects.select_related('owner')
    if can_manage(account):
        return qs.exclude(status=STATUS_DELETED).order_by('-created_at')
    if getattr(account, 'pk', None) is None:
        return qs.none()
    return qs.filter(owner=account).exclude(status=STATUS_DELETED).order_by('-created_at')


def storage_stats(account):
    qs = scoped_files(account)
    return {'count': qs.count(),
            'bytes': sum(item.size for item in qs)}
