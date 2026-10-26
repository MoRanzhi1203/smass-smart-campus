from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect
from django.utils.deprecation import MiddlewareMixin

##################################################
from django.shortcuts import redirect


class AuthMiddleware(MiddlewareMixin):
    """中间件"""

    # def __init__(self, get_response):
    #     self.get_response = get_response
    #
    # def __call__(self, request):

    @staticmethod
    def process_request(request):
        # if request.user.is_authenticated:
        #     if request.user.is_admin:
        #         if not request.path.startswith('/admin/'):
        #             return redirect('/admin/admin/list/')
        #     elif request.user.is_teacher:
        #         if not request.path.startswith('/teacher/'):
        #             return redirect('/teacher/basic/')
        #     elif request.user.is_student:
        #         if not request.path.startswith('/student/'):
        #             return redirect('student/basic/')
        # else:
        #     url = '/login/account/?select='
        if request.path.startswith('/admin/'):
            # pass
            info_dict = request.session.get('info')
            print(info_dict)
            # print(None == 'admin')
            # print()
            if info_dict is None:
                return redirect('/login/account/admin/')

            if info_dict['type'] == 'admin':
                print('可运行')
                # return None 继续向后走
                return
            return redirect('/login/account/admin/')

        elif request.path.startswith('/student/'):
            info_dict = request.session.get('info')

            if info_dict is None:
                return redirect('/login/account/student/')

            if info_dict['type'] == 'student':
                # return None 继续向后走
                return
            return redirect('/login/account/student/')

        elif request.path.startswith('/teacher/'):
            pass

        # response = self.get_response(request)
        # return response
