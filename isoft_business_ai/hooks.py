from . import __version__ as app_version  # noqa: F401

app_name = "isoft_business_ai"
app_title = "Isoft Business AI"
app_publisher = "ISOFT"
app_description = "Conversational business intelligence for ERPNext, backed by verified query tools"
app_icon = "octicon octicon-comment-discussion"
app_color = "#4C5BD4"
app_email = "ai.accounts@isoft.co.ao"
app_license = "MIT"

app_include_css = ["/assets/isoft_business_ai/css/ibai.css"]
app_include_js = [
    "/assets/isoft_business_ai/js/ibai_renderer.js",
    "/assets/isoft_business_ai/js/ibai_widget.js",
]

boot_session = "isoft_business_ai.boot.boot_session"

after_install = "isoft_business_ai.install.after_install"
