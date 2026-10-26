from django.shortcuts import render


def teacher_basic(request):

    return render(request, 'teacher/basic.html')