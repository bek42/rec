import base64
import html as html_lib

from playwright.sync_api import Browser, sync_playwright

_playwright = None
_browser: Browser | None = None


def _get_browser() -> Browser:
    global _playwright, _browser
    if _browser is None:
        _playwright = sync_playwright().start()
        _browser = _playwright.chromium.launch()
    return _browser


def close_browser() -> None:
    global _playwright, _browser
    if _browser:
        _browser.close()
        _browser = None
    if _playwright:
        _playwright.stop()
        _playwright = None


def wrap_email_as_html(
    subject: str,
    sender: str,
    date: str,
    html_body: str | None,
    text_body: str | None,
    images: list[tuple[str, bytes]] | None = None,
) -> str:
    """`images` (content_type, data) pairs are appended after the body, each
    starting on its own page — used for a booking-confirmation-style email
    whose real content is the HTML body (booking ref, driver, fare) with an
    incidental image attachment alongside it (a route map): one logical
    receipt becomes one multi-page PDF instead of a separate PDF per piece."""
    body = html_body if html_body else f"<pre>{html_lib.escape(text_body or '(no body)')}</pre>"
    image_pages = "".join(
        f'<div style="page-break-before:always"><img src="data:{ct};base64,'
        f'{base64.b64encode(data).decode()}" style="max-width:100%"></div>'
        for ct, data in (images or [])
    )
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<style>body{{font-family:-apple-system,Helvetica,Arial,sans-serif;padding:24px;font-size:14px;line-height:1.5;color:#111}}
.meta{{color:#555;border-bottom:1px solid #ccc;margin-bottom:16px;padding-bottom:8px}}</style></head>
<body><div class="meta"><strong>From:</strong> {html_lib.escape(sender)}<br>
<strong>Date:</strong> {html_lib.escape(date)}<br>
<strong>Subject:</strong> {html_lib.escape(subject)}</div>
<div>{body}</div>{image_pages}</body></html>"""


def render_html_to_pdf(html: str) -> bytes:
    browser = _get_browser()
    # Untrusted third-party email HTML — no reason to execute scripts or
    # tracking beacons in a headless render context.
    context = browser.new_context(java_script_enabled=False)
    try:
        page = context.new_page()
        page.set_content(html, wait_until="load")
        return page.pdf(format="A4", print_background=True)
    finally:
        context.close()
