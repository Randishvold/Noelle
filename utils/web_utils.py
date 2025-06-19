# Noelle_Bot/utils/web_utils.py

import aiohttp
import logging
from typing import Optional

_logger = logging.getLogger("noelle_bot.web_utils")
PASTE_API_URL = "https://markdownpasteit.vercel.app/api/paste"

async def upload_to_paste_service(content: str) -> Optional[str]:
    """
    Mengunggah konten teks ke layanan paste dan mengembalikan URL-nya.
    Mengembalikan None jika terjadi kegagalan.
    """
    payload = {"content": content}
    headers = {"Content-Type": "application/json"}

    try:
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.post(PASTE_API_URL, json=payload, timeout=30) as response:
                if response.status == 200:
                    data = await response.json()
                    paste_url = data.get("url")
                    if paste_url:
                        _logger.info(f"Berhasil mengunggah laporan ke paste service. URL: {paste_url}")
                        return paste_url
                    else:
                        _logger.error("API paste service merespons 200 OK tetapi tidak ada URL di body.")
                        return None
                else:
                    error_body = await response.text()
                    _logger.error(f"Gagal mengunggah ke paste service. Status: {response.status}, Body: {error_body}")
                    return None
    except aiohttp.ClientError as e:
        _logger.error(f"Error jaringan saat menghubungi paste service: {e}", exc_info=True)
        return None
    except Exception as e:
        _logger.error(f"Error tak terduga saat mengunggah ke paste service: {e}", exc_info=True)
        return None