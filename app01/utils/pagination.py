"""
自定义的分页组件
以后如果想要使用这个分页组件，你需要做如下几件事：

在视图函数中：
    def pretty_list(request):

        # 1.根据需求去筛选想要的数据
        queryset = models.PrettyNum.objects.filter(**data_dict).order_by('-level')

        # 2.实例化分页对象
        page_object = Pagination(request, queryset)

        context = {
            'queryset': page_object.page_queryset,  # 分页数据
            'page_string': page_object.html()       # 生成页码
        }
        return render(request, 'pretty_list.html', context)

在HTML页面中：

    {% for obj in queryset %}
        {{ obj.xx }}
    {% endfor %}

    {{ page_string }}
"""
from django.utils.safestring import mark_safe


class Pagination(object):

    def __init__(self, request, queryset, page_size=15, page_param='page', plus=5):
        """
        :param request: 请求的对象
        :param queryset: 符合条件的数据（根据这个数据进行分页处理）
        :param page_size: 每页显示多少条数据
        :param page_param: 在URL中传递的获取分页的参数，例如：/pretty/list/?page=6
        :param plus: 页码栏尺度
        """

        # from django.http.request import QueryDict
        import copy
        query_dict = copy.deepcopy(request.GET)
        query_dict._mutable = True
        self.query_dict = query_dict

        self.page_param = page_param

        page = request.GET.get(page_param, '1')
        if page.isdecimal():
            page = int(page)
        else:
            page = 1
        self.page = page
        self.page_size = page_size

        self.start = (page - 1) * page_size
        self.end = page * page_size

        self.page_queryset = queryset[self.start: self.end]

        total_count = queryset.count()
        # 计算总页码
        total_page_count, div = divmod(total_count, page_size)
        if div:
            # 有余数则 页码+1
            total_page_count += 1
        self.total_page_count = total_page_count
        self.plus = plus

    def html(self):
        # 计算出，显示当前页的前5页、后5页

        if self.total_page_count <= (2 * self.plus + 1):
            # 当数据量较少时
            start_page = 1
            end_page = self.total_page_count
        else:
            # 当数据较多时
            if self.page <= self.plus:
                # 当前页<5时（小极值）
                start_page = 1
                end_page = 2 * self.plus + 1
            elif (self.page + self.plus) > self.total_page_count:
                # 当前页+5>总页数（大极值）
                start_page = self.total_page_count - 2 * self.plus
                end_page = self.total_page_count
            else:
                start_page = self.page - self.plus
                end_page = self.page + self.plus

        # 页码
        page_str_list = ['<div style="display: flex; align-items: center; justify-content: center;">'
                         '<ul class="pagination">']

        # 首页
        self.query_dict.setlist(self.page_param, [1])
        prev = '<li><a href="?{}">首页</a></li>'.format(self.query_dict.urlencode())
        page_str_list.append(prev)

        # 上一页
        if self.page > 1:
            self.query_dict.setlist(self.page_param, [self.page - 1])
            prev = '<li><a href="?{}">上一页</a></li>'.format(self.query_dict.urlencode())
        else:
            self.query_dict.setlist(self.page_param, [1])
            prev = '<li><a href="?page={}">上一页</a></li>'.format(self.query_dict.urlencode())
        page_str_list.append(prev)

        # 选择页码
        for i in range(start_page, end_page + 1):
            self.query_dict.setlist(self.page_param, [i])
            if i == self.page:
                ele = '<li class="active"><a href="?{}">{}</a></li>'.format(self.query_dict.urlencode(), i)
            else:
                ele = '<li><a href="?{}">{}</a></li>'.format(self.query_dict.urlencode(), i)
            page_str_list.append(ele)

        # 下一页
        if self.page < self.total_page_count:
            self.query_dict.setlist(self.page_param, [self.page + 1])
            prev = '<li><a href="?{}">下一页</a></li>'.format(self.query_dict.urlencode())
        else:
            self.query_dict.setlist(self.page_param, [self.total_page_count])
            prev = '<li><a href="?{}">下一页</a></li>'.format(self.query_dict.urlencode())
        page_str_list.append(prev)

        # 尾页
        self.query_dict.setlist(self.page_param, [self.total_page_count])
        prev = '<li><a href="?{}">尾页</a></li>'.format(self.query_dict.urlencode())
        page_str_list.append(prev)

        # 跳转框
        # search_string = """
        #     <li>
        #         <form style="float: left; margin-left: -1px" method="get">
        #             <div class="input-group" style="width: 200px">
        #                 <input type="text" name="page" class="form-control" placeholder="页码">
        #                 <span class="input-group-btn">
        #                     <button class="btn btn-default" type="submit">跳转</button>
        #                 </span>
        #             </div>
        #         </form>
        #     </li>
        #     """
        # page_str_list.append(search_string)

        page_str_list.append('</ul>')

        # 共__页
        total_text = '<div style="text-align: center;">' \
                     '<span style="margin: 15px; font-weight: bold;">共 {} 页</span>' \
                     '</div>'.format(self.total_page_count)
        page_str_list.append(total_text)

        # 闭合
        page_str_list.append('</div>')

        page_string = mark_safe(''.join(page_str_list))
        return page_string
