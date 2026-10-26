"""
自定义的分页组件
以后如果想要使用这个分页组件，你需要做如下几件事：

在视图函数中：
    def pretty_list(request):

        # 1.根据需求去筛选想要的数据
        queryset = models.PrettyNum.objects.filter(**data_dict).order_by('-level')

        # 2.实例化分页对象
        page_object = Pagination(request, queryset, page_size)

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
import copy


class Pagination(object):

    def __init__(self, request, queryset, page_size=10, page_param='page'):
        """
        :param request: 请求的对象
        :param queryset: 符合条件的数据（根据这个数据进行分页处理）
        :param page_size: 每页显示多少条数据
        :param page_param: 在URL中传递的获取分页的参数，例如：/pretty/list/?page=6
        """

        query_dict = copy.deepcopy(request.POST)
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

        self.total_count = queryset.count()
        # 计算总页码
        total_page_count, div = divmod(self.total_count, page_size)
        if div:
            # 有余数则 页码+1
            total_page_count += 1
        self.total_page_count = total_page_count

    def html(self):
        # 计算出，显示当前页的页码链

        if self.total_page_count <= 9:
            # 当数据量较少时
            start_page = 1
            end_page = self.total_page_count
        else:
            # 当数据较多时
            if self.page <= 4:
                # 当前页<5时（小极值）
                start_page = 1
                end_page = 7
            elif (self.page + 4) > self.total_page_count:
                # 当前页+5>总页数（大极值）
                start_page = self.total_page_count - 6
                end_page = self.total_page_count
            else:
                start_page = self.page - 2
                end_page = self.page + 2

        # 页码
        page_str_list = ['<div class="datatable-bottom">',
                         '<div class="datatable-info">显示 {start} 至 {end} 条信息（共有 {rows} 条）</div>',
                         '<nav class="datatable-pagination"><ul class="datatable-pagination-list">']

        # 上一页
        if self.page > 1:
            self.query_dict.setlist(self.page_param, [self.page - 1])
            prev = '<li class="datatable-pagination-list-item">' \
                   '<a href="?{}">&lt;</a>' \
                   '</li>'.format(self.query_dict.urlencode())
            page_str_list.append(prev)

        # 首页页码
        if self.page > 4 and self.total_page_count > 9:
            self.query_dict.setlist(self.page_param, [1])
            prev = '<li class="datatable-pagination-list-item">' \
                   '<a href="?{}">1</a>' \
                   '</li>' \
                   '<li class="datatable-pagination-list-item datatable-ellipsis datatable-disabled">' \
                   '<button class="datatable-pagination-list-item-link">…</button>' \
                   '</li>'.format(self.query_dict.urlencode())
            page_str_list.append(prev)

        # 选择页码
        for i in range(start_page, end_page + 1):
            self.query_dict.setlist(self.page_param, [i])
            if i == self.page:
                ele = '<li class="datatable-pagination-list-item datatable-active">' \
                      '<a href="?{}">{}</a>' \
                      '</li>'.format(self.query_dict.urlencode(), i)
            else:
                ele = '<li class="datatable-pagination-list-item">' \
                      '<a href="?{}">{}</a>' \
                      '</li>'.format(self.query_dict.urlencode(), i)
            page_str_list.append(ele)

        # 尾页页码
        if self.page < self.total_page_count - 3 and self.total_page_count > 9:
            self.query_dict.setlist(self.page_param, [self.total_page_count])
            prev = '<li class="datatable-pagination-list-item datatable-ellipsis datatable-disabled">' \
                   '<button class="datatable-pagination-list-item-link">…</button>' \
                   '</li>' \
                   '<li class="datatable-pagination-list-item">' \
                   '<a href="?{}">{}</a>' \
                   '</li>'.format(self.query_dict.urlencode(), self.total_page_count)
            page_str_list.append(prev)

        # 下一页
        if self.page < self.total_page_count:
            self.query_dict.setlist(self.page_param, [self.page + 1])
            prev = '<li class="datatable-pagination-list-item">' \
                   '<a href="?{}">&gt;</a>' \
                   '</li>'.format(self.query_dict.urlencode())
            page_str_list.append(prev)

        page_str_list.append('</ul></nav>')

        # 闭合
        page_str_list.append('</div>')

        # 对下方的信息条目进行格式化输出
        page_string = mark_safe(''.join(page_str_list).format(
            start=(self.page - 1) * 10 + 1,
            end=self.total_count if self.page == self.total_page_count else self.page * 10,
            rows=self.total_count
        ))

        return page_string
