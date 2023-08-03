#!/bin/env python
"""Gravatar profile picture"""
__author__ = "Badreddine LEJMI <badreddine@ankaboot.fr>"
__copyright__ = "Ankaboot"
__license__ = "AGPL"

from hashlib import md5

from loguru import logger as log
from curl_cffi.requests import AsyncSession, RequestsError

# 400x400 is the de facto standard size for profile picture (linkedin, twitter)
# make it easier for comparison purpose
GRAVATAR_SIZE = 400
GRAVATAR_URL = "https://www.gravatar.com/avatar/{hashed_email}?d=404&s={size}"


def email_hash(email: str) -> str:
    """
    Returns a md5 hash from a string.
    >>> md5_hash('myemailaddress@example.com')
    '0bc83cb571cd1c50ba6f3e8a78ef1346'
    """
    return md5(email.encode("utf-8").lower(), usedforsecurity=False).hexdigest()


async def gravatar(email: str, check: bool = True) -> str:
    """Returns a valid Gravatar URL or None if not found

    Args:
        email (str): email address
        check (bool): check if the profile picture is available

    Returns:
        str: Gravatar URL
    """
    gravatar_image_url = GRAVATAR_URL.format(
        hashed_email=email_hash(email), size=GRAVATAR_SIZE
    )

    # if no check is needed that's over
    if not check:
        return gravatar_image_url

    # let's check if the profile picture is available
    async with AsyncSession() as s:
        try:
            r = await s.get(gravatar_image_url)
        except RequestsError as e:
            log.error(f" {e}. email: {email}, url: {gravatar_image_url}")
            return None
        if r.ok:
            return gravatar_image_url


# command line usage only for dev purpose
if __name__ == "__main__":
    import sys

    url = gravatar(sys.argv[1])

    print(url)
    if not url:
        sys.exit()

    # taken from https://github.com/nikhilkumarsingh/terminal-image-viewer
    # Copyright Nikhil Kumarsingh
    try:
        from io import BytesIO

        import numpy as np
        from PIL import Image
    except ImportError:
        sys.exit()

    def get_ansi_color_code(r, g, b):
        if r == g == b:
            if r < 8:
                return 16
            if r > 248:
                return 231
            return round(((r - 8) / 247) * 24) + 232
        return (
            16
            + (36 * round(r / 255 * 5))
            + (6 * round(g / 255 * 5))
            + round(b / 255 * 5)
        )

    def get_color(r, g, b):
        return "\x1b[48;5;{}m \x1b[0m".format(int(get_ansi_color_code(r, g, b)))

    def show_image(url_image: str, height: int = 100):
        s = AsyncSession()
        response = await s.get(url_image)
        img = Image.open(BytesIO(response.content))
        img.convert("RGB")

        width = int((img.width / img.height) * height)

        img = img.resize((width, height), Image.ANTIALIAS)
        img_arr = np.asarray(img)
        h, w, _ = img_arr.shape

        for x in range(h):
            for y in range(w):
                pix = img_arr[x][y]
                print(get_color(pix[0], pix[1], pix[2]), sep="", end="")
            print()

    show_image(url, int(GRAVATAR_SIZE / 10))
