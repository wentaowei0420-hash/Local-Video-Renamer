ENRICHED_STATUS = '已补全'
UNENRICHED_STATUS = '未补全'
FAILED_STATUS = '补全失败'
NO_SEARCH_RESULTS_STATUS = '无搜索结果'
NO_VIDEO_DETAIL_STATUS = '无视频详情'


def is_no_result_status(value):
    text = str(value or '').strip()
    return text in (
        NO_SEARCH_RESULTS_STATUS,
        NO_VIDEO_DETAIL_STATUS,
    )
