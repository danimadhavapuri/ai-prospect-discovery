"""Registry of all platform discovery adapters."""

from app.platforms.base import BasePlatform
from app.platforms.facebook import FacebookPlatform
from app.platforms.google import GooglePlatform
from app.platforms.instagram import InstagramPlatform
from app.platforms.linkedin import LinkedInPlatform
from app.platforms.threads import ThreadsPlatform
from app.platforms.whatsapp import WhatsAppPlatform
from app.platforms.x_platform import XPlatform
from app.platforms.youtube import YouTubePlatform

ALL_PLATFORMS: list[BasePlatform] = [
    LinkedInPlatform(),
    XPlatform(),
    YouTubePlatform(),
    InstagramPlatform(),
    WhatsAppPlatform(),
    FacebookPlatform(),
    ThreadsPlatform(),
    GooglePlatform(),
]

__all__ = [
    "BasePlatform",
    "LinkedInPlatform",
    "XPlatform",
    "YouTubePlatform",
    "InstagramPlatform",
    "WhatsAppPlatform",
    "FacebookPlatform",
    "ThreadsPlatform",
    "GooglePlatform",
    "ALL_PLATFORMS",
]
