"""S14 页面层：安全文件上传、下载与删除。"""
from __future__ import annotations

from functools import wraps
from urllib.parse import quote

from django.conf import settings
from django.http import FileResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST

from . import services
from .models import PURPOSES, UploadedFile


def _login_url():
    return getattr(settings, 'LOGIN_URL', '/r21/login/')


def require_login(view):
    @wraps(view)
    def _wrapped(request, *args, **kwargs):
        if not getattr(request.user, 'is_authenticated', False):
            target = request.get_full_path()
            return redirect('{}?next={}'.format(_login_url(), quote(target)))
        return view(request, *args, **kwargs)

    return _wrapped


def _forbidden(request, message='当前账号没有访问该页面的权限'):
    return render(request, 's14/forbidden.html', {'message': message}, status=403)


def _flash(request):
    return {
        'ok_message': request.GET.get('ok', ''),
        'error_message': request.GET.get('error', ''),
    }


@require_GET
@require_login
def file_list(request):
    files = list(services.scoped_files(request.user)[:100])
    return render(request, 's14/files.html', {
        'files': files,
        'purposes': PURPOSES,
        'stats': services.storage_stats(request.user),
        'can_manage': services.can_manage(request.user),
        **_flash(request),
    })


@require_POST
@require_login
def file_upload(request):
    uploaded = request.FILES.get('file')
    purpose = (request.POST.get('purpose') or 'attachment').strip()
    if uploaded is None:
        return redirect('/uploads/?error={}'.format(quote('请选择要上传的文件')))
    try:
        services.store(uploaded, request.user, purpose,
                       declared_type=getattr(uploaded, 'content_type', ''))
    except services.UploadError as exc:
        return redirect('/uploads/?error={}'.format(quote(str(exc))))
    return redirect('/uploads/?ok={}'.format(quote('上传成功（已存入私有目录）')))


@require_GET
@require_login
def file_download(request, pk):
    upload = get_object_or_404(UploadedFile, pk=pk)
    try:
        handle = services.open_upload(upload, request.user)
    except services.PermissionDenied:
        return _forbidden(request, '只能下载自己的文件')
    except services.UploadError as exc:
        return _forbidden(request, str(exc))
    response = FileResponse(handle, as_attachment=True,
                            filename=upload.original_name)
    response['X-Content-Type-Options'] = 'nosniff'
    return response


@require_POST
@require_login
def file_delete(request, pk):
    upload = get_object_or_404(UploadedFile, pk=pk)
    try:
        services.delete_upload(upload, request.user)
    except services.PermissionDenied:
        return _forbidden(request, '只能删除自己的文件')
    except services.UploadError as exc:
        return redirect('/uploads/?error={}'.format(quote(str(exc))))
    return redirect('/uploads/?ok={}'.format(quote('文件已删除')))
