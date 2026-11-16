"""URL repair and error-page detection in the browser server.

Job links are routinely copied one encoding layer too deep, so the whole query
arrives encoded (`apply?jobId%3D...%26loc%3DGB`). Google answers that with a bare
400 page. The server now decodes it once and reports an error page instead of
telling the agent it navigated successfully.
"""
import importlib.util
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER = os.path.join(ROOT, "tools", "camoufox_server.py")


def _server():
    spec = importlib.util.spec_from_file_location("camoufox_server_under_test", SERVER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_a_double_encoded_query_is_decoded_once():
    srv = _server()
    bad = ("https://www.google.com/about/careers/applications/apply?"
           "jobId%3DCIU%253D%253D_V2%26loc%3DGB%26title%3DMigration%2Band%2BTransformation")
    assert srv._repair_url(bad) == (
        "https://www.google.com/about/careers/applications/apply?"
        "jobId=CIU%3D%3D_V2&loc=GB&title=Migration+and+Transformation")


def test_a_normal_url_is_left_alone():
    srv = _server()
    for url in ("https://example.test/apply?jobId=123&loc=SE",
                "https://example.test/path",
                "https://www.linkedin.com/jobs/view/4486028571/"):
        assert srv._repair_url(url) == url


def test_an_error_page_is_reported_as_a_failure():
    srv = _server()
    hint = srv._error_page("Error 400 (Bad Request)!!1", "")
    assert "error page" in hint and "malformed" in hint
    assert srv._error_page("That's an error", "") != ""
    assert srv._error_page("Apply - Acme Corp", "") == ""
    assert srv._error_page("", "") == ""
