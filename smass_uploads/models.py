"""S14：安全文件上传（隔离模块）。

防护清单
--------
1. **扩展名白名单**：按用途限制可上传类型，未知/可执行类型一律拒绝；
2. **文件签名校验**：PNG/JPEG/PDF/ZIP(docx/xlsx) 必须匹配 magic number，
   防止"改扩展名绕过"；
3. **大小上限**：单文件不超过 ``MAX_BYTES``；
4. **解压炸弹防护**：ZIP 类文件限制条目数、解压总大小与压缩比；
5. **文件名清洗**：``basename`` + 去控制字符 + 限制长度，落盘用 UUID 重命名；
6. **私有存储**：文件存放在 ``SMASS_PRIVATE_MEDIA_ROOT``，不经公共 MEDIA URL 暴露，
   下载必须走鉴权视图；
7. **归属校验**：只有上传者本人或管理员可下载/删除；
8. **审计**：上传、下载、删除、拒绝都写日志。
"""
from __future__ import annotations

from django.db import models

PURPOSE_AVATAR = 'avatar'
PURPOSE_ATTACHMENT = 'attachment'
PURPOSE_IMPORT = 'import'
PURPOSE_REPORT = 'report'
PURPOSES = (
    (PURPOSE_AVATAR, '头像'),
    (PURPOSE_ATTACHMENT, '附件'),
    (PURPOSE_IMPORT, '导入文件'),
    (PURPOSE_REPORT, '导出/报告'),
)

STATUS_READY = 'ready'
STATUS_QUARANTINED = 'quarantined'
STATUS_DELETED = 'deleted'
FILE_STATUS = (
    (STATUS_READY, '可用'),
    (STATUS_QUARANTINED, '已隔离'),
    (STATUS_DELETED, '已删除'),
)


class UploadedFile(models.Model):
    owner = models.ForeignKey(
        'r21_account.Account', verbose_name='上传者', on_delete=models.PROTECT,
        related_name='uploaded_files')
    purpose = models.CharField('用途', max_length=16, choices=PURPOSES,
                                default=PURPOSE_ATTACHMENT)

    original_name = models.CharField('原始文件名', max_length=255)
    stored_name = models.CharField('存储文件名', max_length=255, unique=True)
    content_type = models.CharField('声明的 MIME', max_length=100, blank=True, default='')
    size = models.PositiveBigIntegerField('大小（字节）', default=0)
    sha256 = models.CharField('SHA-256', max_length=64, db_index=True)

    status = models.CharField('状态', max_length=16, choices=FILE_STATUS,
                              default=STATUS_READY)
    meta = models.JSONField('校验信息', default=dict, blank=True)
    created_at = models.DateTimeField('上传时间', auto_now_add=True)

    class Meta:
        verbose_name = '上传文件'
        verbose_name_plural = verbose_name
        indexes = [
            models.Index(fields=['owner', 'status']),
            models.Index(fields=['purpose', 'status']),
        ]

    def __str__(self):
        return '{} ({})'.format(self.original_name, self.purpose)
