def minimize_browser_window_if_needed(page, headless):
    if headless or page is None:
        return

    try:
        cdp_session = page.context.new_cdp_session(page)
        window_info = cdp_session.send('Browser.getWindowForTarget')
        window_id = window_info.get('windowId')
        if not window_id:
            return
        cdp_session.send(
            'Browser.setWindowBounds',
            {
                'windowId': window_id,
                'bounds': {'windowState': 'minimized'},
            },
        )
    except Exception:
        # Best effort only. If the browser/channel does not expose window
        # controls through CDP, scraping should continue normally.
        return
