from pathlib import Path

import ip2region.util as util
from ip2region.searcher import new_with_buffer

_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_XDB = _ROOT / "ip2region.xdb"
_searcher = None

def lookup(ip: str) -> str:
    """返回归属地字符串，如 '中国|0|上海|上海市|电信'，失败返回空字符串"""
    global _searcher
    try:
        if _searcher is None:
            c_buff = util.load_content_from_file(db_file=str(_XDB))
            header = util.Header(c_buff[:util.HeaderInfoLength])
            version = util.version_from_header(header)
            _searcher = new_with_buffer(version, c_buff)
        return _searcher.search(ip) or ""
    except Exception:
        return ""
