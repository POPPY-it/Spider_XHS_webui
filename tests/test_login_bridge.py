"""login_bridge 的游客会话识别逻辑。"""

from webui.login_bridge import _resolve_user


def test_guest_session_returns_empty():
    assert _resolve_user({"data": {"guest": True}}) == {}


def test_missing_data_returns_empty_user():
    # 无数据且非 guest → 空用户 dict（非空，避免误判为未登录）
    assert _resolve_user({}) == {"nickname": "", "red_id": "", "avatar": ""}
    assert _resolve_user(None) == {"nickname": "", "red_id": "", "avatar": ""}
    assert _resolve_user({"data": {}}) == {"nickname": "", "red_id": "", "avatar": ""}


def test_real_user_parsed():
    r = _resolve_user({
        "data": {
            "nickname": "喵喵",
            "red_id": "869646583",
            "basic_info": {"imageb": "http://img/x.jpg"},
        }
    })
    assert r["nickname"] == "喵喵"
    assert r["red_id"] == "869646583"
    assert r["avatar"] == "http://img/x.jpg"


def test_avatar_fallback_images():
    r = _resolve_user({"data": {"nickname": "A", "red_id": "", "basic_info": {"images": "http://i/y.jpg"}}})
    assert r["avatar"] == "http://i/y.jpg"
    assert r["nickname"] == "A"
