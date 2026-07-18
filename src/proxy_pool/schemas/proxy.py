from datetime import datetime, timezone
from pydantic import BaseModel, field_validator

class Proxy(BaseModel):
    host: str
    port: int
    protocol: str = "http"      # http / https / socks5
    score: int = 10             # init=10, +10 on pass (max 100), -20 on fail
    ping: int = 0               # response time in ms
    source: str = ""            # fetcher source name
    anonymous: bool = True
    region: str = ""            # geo region, set on first successful validation
    created_at: str = ""
    last_check: str = ""

    def model_post_init(self, __context) -> None:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        if not self.created_at:
            self.created_at = now
        if not self.last_check:
            self.last_check = now

    @field_validator("protocol")
    @classmethod
    def validate_protocol(cls, v: str) -> str:
        v = v.lower()
        if v not in ("http", "https", "socks4", "socks5"):
            return "http"
        return v

    @field_validator("port")
    @classmethod
    def validate_port(cls, v: int) -> int:
        if not (1 <= v <= 65535):
            raise ValueError(f"Invalid port: {v}")
        return v

    @property
    def string(self) -> str:
        """Redis Hash field key: 'ip:port'"""
        return f"{self.host}:{self.port}"

    @property
    def url(self) -> str:
        # SOCKS proxies use socks4:// / socks5://; HTTP/HTTPS proxies both connect via http://
        scheme = self.protocol if self.protocol in ("socks4", "socks5") else "http"
        return f"{scheme}://{self.host}:{self.port}"
