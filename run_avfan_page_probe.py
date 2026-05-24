import json

from app.tools.avfan_page_probe import probe_url


# 直接在这里填写你要测试的 AVFan 链接。
TARGET_URL = 'https://avfan.com/search?q=%E4%BC%8A%E7%B9%94%E6%B6%BC%E5%AD%90&st=cast'

# 是否显示浏览器窗口。
SHOW_BROWSER = True

# 最多输出多少行页面可见文本预览。
MAX_LINES = 820

# 最多输出多少条列表/链接结果。
MAX_ENTRIES = 90


def main():
    if not TARGET_URL.strip():
        raise ValueError('请先在 run_avfan_page_probe.py 中填写 TARGET_URL')

    result = probe_url(
        url=TARGET_URL.strip(),
        show_browser=SHOW_BROWSER,
        max_lines=MAX_LINES,
        max_entries=MAX_ENTRIES,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
